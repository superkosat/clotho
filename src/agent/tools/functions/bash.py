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
    # rm with recursive+force flags targeting root or home
    if re.search(r'\brm\b.*-[^\s]*r[^\s]*f[^\s]*\s+/', command) or \
       re.search(r'\brm\b.*-[^\s]*f[^\s]*r[^\s]*\s+/', command):
        return False, "Command contains dangerous pattern: rm -rf on root path"

    # 'format' as a standalone command token (the disk format utility),
    # not as part of a flag (--format), query param (&format=), or word
    if re.search(r'(?<![=&\-\w])format(?![=\w])', command):
        return False, "Command contains dangerous pattern: format"

    # fork bomb
    if ':(){:|:&};:' in command:
        return False, "Command contains dangerous pattern: fork bomb"

    return True, None


def win_to_wsl_path(path: str) -> str:
    """Convert a Windows path like C:\\Users\\foo to /mnt/c/Users/foo"""
    drive, rest = path[0].lower(), path[2:]
    return f"/mnt/{drive}{rest.replace(chr(92), '/')}"


def translate_paths_for_wsl(command: str) -> str:
    """Find Windows-style absolute paths in a command and convert them to WSL paths."""
    # Require backslash OR a single forward slash NOT followed by another slash,
    # so that URL schemes like https:// are not matched as drive paths.
    return re.sub(
        r'[A-Za-z]:[\\\/](?!\/)[^\s\'"]*',
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
