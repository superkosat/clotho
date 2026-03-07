"""Daemon mode runner for Clotho gateway."""

import subprocess
import sys


def run_daemon(host: str = "127.0.0.1", port: int = 8000):
    """Start the gateway as a detached background process.

    Spawns uvicorn in a new process group detached from the terminal,
    then returns immediately so the shell prompt is restored.

    Args:
        host: Gateway host address
        port: Gateway port number
    """
    cmd = [
        sys.executable, "-m", "uvicorn",
        "gateway.app:create_app",
        "--factory",
        "--host", host,
        "--port", str(port),
        "--log-level", "warning",
    ]

    if sys.platform == "win32":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(cmd, creationflags=flags, close_fds=True)
    else:
        proc = subprocess.Popen(cmd, start_new_session=True, close_fds=True)

    print(f"Gateway started on {host}:{port} [{proc.pid}]")


def run_server(host: str = "127.0.0.1", port: int = 8000):
    """Run the gateway server in the foreground (blocks until stopped).

    Args:
        host: Gateway host address
        port: Gateway port number
    """
    import uvicorn
    print(f"Starting Clotho gateway on {host}:{port}")
    print("Press Ctrl+C to stop")
    uvicorn.run(
        "gateway.app:create_app",
        factory=True,
        host=host,
        port=port,
        log_level="info",
    )
