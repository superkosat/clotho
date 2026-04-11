"""Gateway subprocess lifecycle management."""

import subprocess
import sys
import time
from pathlib import Path

import requests

LOG_FILE = Path.home() / ".clotho" / "gateway.log"


class GatewayManager:
    """Manages gateway subprocess lifecycle."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8000):
        """Initialize gateway manager.

        Args:
            host: Gateway host address
            port: Gateway port number
        """
        self.host = host
        self.port = port
        self.process: subprocess.Popen | None = None
        self._log_fh = None

    def start(self):
        """Start gateway subprocess.

        Raises:
            RuntimeError: If gateway fails to start within timeout
        """
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._log_fh = LOG_FILE.open("a", encoding="utf-8")

        # Run uvicorn via Python module to avoid shell issues
        cmd = [
            sys.executable, "-m", "uvicorn",
            "gateway.app:create_app",
            "--factory",
            "--host", self.host,
            "--port", str(self.port),
            "--log-level", "info",
        ]

        self.process = subprocess.Popen(
            cmd,
            stdout=self._log_fh,
            stderr=self._log_fh,
        )

        # Wait for server to be ready (max 10s)
        for _ in range(20):
            try:
                response = requests.get(
                    f"http://{self.host}:{self.port}/health",
                    timeout=1
                )
                if response.status_code == 200:
                    return True
            except (requests.ConnectionError, requests.Timeout):
                time.sleep(0.5)

        # If we get here, gateway failed to start
        self.stop()
        raise RuntimeError("Gateway failed to start within 10 seconds")

    def stop(self):
        """Stop gateway subprocess."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self._log_fh:
            self._log_fh.close()
            self._log_fh = None

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, *args):
        """Context manager exit."""
        self.stop()
