import re
import subprocess
import sys

from sandbox.config import is_sandbox_enabled

# Global sandbox instance (set by controller)
_active_sandbox = None


def set_sandbox_instance(sandbox):
    """Set the active sandbox instance for this session."""
    global _active_sandbox
    _active_sandbox = sandbox


def get_sandbox_instance():
    """Get the active sandbox instance."""
    return _active_sandbox


def validate_command(command: str) -> tuple[bool, str | None]:
    """Block dangerous commands."""
    dangerous_patterns = ['rm -rf /', 'format', ':(){:|:&};:']
    for pattern in dangerous_patterns:
        if pattern in command:
            return False, f"Command contains dangerous pattern: {pattern}"
    return True, None


def win_to_wsl_path(path: str) -> str:
    """Convert a Windows path like C:\\Users\\foo to /mnt/c/Users/foo"""
    drive, rest = path[0].lower(), path[2:]
    return f"/mnt/{drive}{rest.replace(chr(92), '/')}"


def translate_paths_for_wsl(command: str) -> str:
    """Find Windows-style absolute paths in a command and convert them to WSL paths."""
    return re.sub(
        r'[A-Za-z]:[\\\/][^\s\'"]*',
        lambda m: win_to_wsl_path(m.group()),
        command
    )


def bash_func(command: str) -> str:
    is_safe, remark = validate_command(command)
    if not is_safe:
        return remark

    # Use sandbox if enabled and available
    sandbox_enabled = is_sandbox_enabled()

    if sandbox_enabled:
        sandbox = get_sandbox_instance()

        if sandbox and sandbox.is_running:
            try:
                return sandbox.exec(command)
            except Exception as e:
                return f"Sandbox error: {e}"
        else:
            return "Error: Sandbox not initialized"

    # Fallback to direct execution
    if sys.platform == 'win32':
        command = translate_paths_for_wsl(command)
        shell_cmd = ['wsl', 'bash', '-c', command]
    else:
        shell_cmd = ['bash', '-c', command]

    result = subprocess.run(
        shell_cmd,
        capture_output=True,
        text=True,
        timeout=30,
        encoding='utf-8',
        errors='replace'  # replace undecodable chars instead of crashing
    )

    stdout = result.stdout or ''
    stderr = result.stderr or ''
    return stdout + stderr
