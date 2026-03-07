"""Sandbox class for secure Docker-based code execution."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import docker
from docker.models.containers import Container

from sandbox.exceptions import (
    SandboxDockerError,
    SandboxImageNotFoundError,
    SandboxNotRunningError,
    WorkspaceAccessError,
)


@dataclass
class SandboxConfig:
    """Configuration for sandbox security constraints."""

    # Resource limits
    memory_limit: str = "512m"  # 512MB default
    cpu_quota: int = 100000  # 1.0 CPU cores (100000/100000)
    cpu_period: int = 100000
    timeout_seconds: int = 30

    # Security settings
    network_enabled: bool = False
    read_only_root: bool = True
    drop_capabilities: list[str] = field(default_factory=lambda: ["ALL"])
    seccomp_profile: Optional[dict] = None  # Custom seccomp

    # Workspace settings
    workspace_path: Optional[str] = None  # Host path to mount
    workspace_mode: Literal["ro", "rw"] = "rw"

    # Image settings
    image_name: str = "clotho-sandbox:latest"
    user_uid: int = 1000  # Non-root user inside container
    user_gid: int = 1000


class Sandbox:
    """
    Manages a Docker container for safe code execution.

    Lifecycle:
    - Created per chat session via __enter__ or explicit start()
    - Persists across multiple exec() calls
    - Cleanup via __exit__ or explicit cleanup()

    Security Features:
    - Non-root execution (uid 1000)
    - Capability dropping
    - Memory/CPU limits
    - Read-only root filesystem
    - Network isolation by default
    - Workspace-only file access
    """

    def __init__(
        self,
        config: Optional[SandboxConfig] = None,
        session_id: Optional[str] = None,
    ):
        """
        Initialize sandbox manager.

        Args:
            config: Security and resource configuration
            session_id: Unique identifier for this sandbox (for naming)
        """
        self.config = config or SandboxConfig()
        self.session_id = session_id or "default"
        self.client: Optional[docker.DockerClient] = None
        self.container: Optional[Container] = None
        self._is_running = False

    def __enter__(self):
        """Context manager entry - starts container."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleans up container."""
        self.cleanup()

    def start(self) -> None:
        """
        Create and start the sandbox container.

        Raises:
            SandboxDockerError: If Docker daemon unreachable
            SandboxImageNotFoundError: If sandbox image not built
        """
        if self._is_running:
            return

        try:
            self.client = docker.from_env()
        except docker.errors.DockerException:
            raise SandboxDockerError()

        # Validate workspace path
        workspace_path = self._resolve_workspace_path()

        # Check if image exists (use list() instead of get() for Windows compatibility)
        images = self.client.images.list()
        image_exists = any(
            self.config.image_name in image.tags
            for image in images
        )
        if not image_exists:
            raise SandboxImageNotFoundError()

        # Check if container already exists with this session ID
        container_name = f"clotho-sandbox-{self.session_id}"
        try:
            existing = self.client.containers.get(container_name)
            if existing.status == "running":
                # Reuse existing running container
                self.container = existing
                self._is_running = True
                return
            else:
                # Remove stopped container
                existing.remove(force=True)
        except docker.errors.NotFound:
            # Container doesn't exist, will create new one
            pass

        # Build container configuration
        container_config = {
            "image": self.config.image_name,
            "name": container_name,
            "detach": True,
            "stdin_open": True,
            "tty": True,
            "user": f"{self.config.user_uid}:{self.config.user_gid}",
            "working_dir": "/workspace",
            # Resource limits
            "mem_limit": self.config.memory_limit,
            "cpu_quota": self.config.cpu_quota,
            "cpu_period": self.config.cpu_period,
            # Security hardening
            "cap_drop": self.config.drop_capabilities,
            "read_only": self.config.read_only_root,
            "network_disabled": not self.config.network_enabled,
            "security_opt": self._build_security_opts(),
            # Volumes
            "volumes": {
                workspace_path: {"bind": "/workspace", "mode": self.config.workspace_mode}
            },
            # Tmpfs for writable temp space (read-only root needs this)
            "tmpfs": {"/tmp": "rw,noexec,nosuid,size=100m"},
            # Keep container alive
            "command": "tail -f /dev/null",
            # Auto-remove on stop
            "auto_remove": True,
        }

        self.container = self.client.containers.run(**container_config)
        self._is_running = True

    def exec(
        self,
        command: str,
        timeout: Optional[int] = None,
        env: Optional[dict[str, str]] = None,
        working_dir: Optional[str] = None,
    ) -> str:
        """
        Execute a shell command inside the sandbox.

        Args:
            command: Shell command to execute
            timeout: Override default timeout (seconds)
            env: Environment variables to set
            working_dir: Working directory inside container (default: /workspace)

        Returns:
            Combined stdout and stderr output

        Raises:
            SandboxNotRunningError: If container not running
            docker.errors.APIError: On Docker API failures
        """
        if not self._is_running or not self.container:
            raise SandboxNotRunningError()

        timeout = timeout or self.config.timeout_seconds
        working_dir = working_dir or "/workspace"

        # Execute command
        exit_code, output = self.container.exec_run(
            cmd=["bash", "-c", command],
            environment=env,
            workdir=working_dir,
            demux=False,  # Combine stdout/stderr
            user=f"{self.config.user_uid}:{self.config.user_gid}",
        )

        # Decode output
        result = output.decode("utf-8", errors="replace") if output else ""

        # Include exit code in error case
        if exit_code != 0:
            result = f"[Exit code: {exit_code}]\n{result}"

        return result

    def cleanup(self) -> None:
        """
        Stop and remove the sandbox container.

        Safe to call multiple times. Handles errors gracefully.
        """
        if not self._is_running:
            return

        try:
            if self.container:
                self.container.stop(timeout=5)
                # Container auto-removes due to auto_remove=True
        except Exception as e:
            # Log but don't raise - cleanup should be best-effort
            # Only print if not in Python shutdown (avoid "sys.meta_path is None" errors)
            try:
                import sys
                if sys is not None and sys.meta_path is not None:
                    print(f"Warning: Error during sandbox cleanup: {e}")
            except:
                pass  # Suppress all errors during shutdown
        finally:
            self.container = None
            self._is_running = False
            if self.client:
                self.client.close()
            self.client = None

    def install_packages(
        self, packages: list[str], manager: Literal["apk", "pip", "npm"] = "apk"
    ) -> str:
        """
        Install packages inside the sandbox.

        Requires network_enabled=True in config.

        Args:
            packages: List of package names
            manager: Package manager to use

        Returns:
            Installation output

        Raises:
            RuntimeError: If network disabled
        """
        if not self.config.network_enabled:
            raise RuntimeError(
                "Network disabled. Set network_enabled=True to install packages."
            )

        if manager == "apk":
            cmd = f"apk add --no-cache {' '.join(packages)}"
        elif manager == "pip":
            cmd = f"pip install --no-cache-dir {' '.join(packages)}"
        elif manager == "npm":
            cmd = f"npm install -g {' '.join(packages)}"
        else:
            raise ValueError(f"Unknown package manager: {manager}")

        return self.exec(cmd, timeout=300)  # Longer timeout for installs

    def _resolve_workspace_path(self) -> str:
        """Resolve and validate workspace path."""
        if self.config.workspace_path:
            path = Path(self.config.workspace_path).resolve()
        else:
            path = Path.cwd()

        if not path.exists():
            raise ValueError(f"Workspace path does not exist: {path}")

        return str(path)

    def _build_security_opts(self) -> list[str]:
        """Build Docker security options."""
        opts = []

        # No new privileges
        opts.append("no-new-privileges:true")

        # AppArmor profile (if available on host)
        # opts.append("apparmor=docker-default")

        return opts

    @property
    def is_running(self) -> bool:
        """Check if sandbox container is running."""
        return self._is_running and self.container is not None
