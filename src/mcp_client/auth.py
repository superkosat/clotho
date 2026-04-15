"""
OAuth 2.1 helpers for MCP client connections.

Provides:
  - FileTokenStorage  — persists OAuth tokens and client registration to disk
  - CallbackServer    — minimal asyncio HTTP server that captures the auth code redirect
  - open_browser      — redirect handler that opens the authorization URL in the OS browser
  - find_free_port    — binds to port 0 to discover an available ephemeral port
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

logger = logging.getLogger(__name__)

TOKEN_DIR = Path.home() / ".clotho" / "mcp" / "tokens"

_CALLBACK_HTML = (
    b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n"
    b"<html><body><h2>Authorization complete.</h2>"
    b"<p>You can close this tab and return to Clotho.</p></body></html>"
)
_ERROR_HTML = (
    b"HTTP/1.1 400 Bad Request\r\nContent-Type: text/html\r\n\r\n"
    b"<html><body><h2>Authorization failed.</h2>"
    b"<p>No authorization code received.</p></body></html>"
)


# ---------------------------------------------------------------------------
# Token storage
# ---------------------------------------------------------------------------

class FileTokenStorage:
    """Persists OAuth tokens and client registration info to ~/.clotho/mcp/tokens/<name>.json.

    Implements the TokenStorage protocol required by mcp.client.auth.OAuthClientProvider.
    """

    def __init__(self, server_name: str) -> None:
        self._path = TOKEN_DIR / f"{server_name}.json"

    # -- internal helpers ---------------------------------------------------

    def _load(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, data: dict) -> None:
        TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            import os
            os.chmod(self._path, 0o600)
        except OSError:
            pass  # Windows doesn't support Unix permissions

    # -- TokenStorage protocol ----------------------------------------------

    async def get_tokens(self) -> OAuthToken | None:
        raw = self._load().get("tokens")
        if not raw:
            return None
        try:
            return OAuthToken.model_validate(raw)
        except Exception:
            return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        data = self._load()
        data["tokens"] = tokens.model_dump(mode="json")
        self._save(data)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        raw = self._load().get("client_info")
        if not raw:
            return None
        try:
            return OAuthClientInformationFull.model_validate(raw)
        except Exception:
            return None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        data = self._load()
        data["client_info"] = client_info.model_dump(mode="json")
        self._save(data)

    def clear(self) -> None:
        """Remove all stored tokens and client info (force re-auth on next connect)."""
        if self._path.exists():
            self._path.unlink()


# ---------------------------------------------------------------------------
# Callback server
# ---------------------------------------------------------------------------

class CallbackServer:
    """Minimal asyncio HTTP server that captures the OAuth authorization code redirect.

    Usage:
        server = CallbackServer(port)
        await server.start()
        ...
        code, state = await server.wait_for_callback()
        await server.stop()
    """

    def __init__(self, port: int) -> None:
        self._port = port
        self._server: asyncio.Server | None = None
        self._result: asyncio.Future[tuple[str, str | None]] | None = None

    @property
    def port(self) -> int:
        return self._port

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._result = loop.create_future()
        self._server = await asyncio.start_server(
            self._handle_request, "127.0.0.1", self._port
        )
        logger.debug("OAuth callback server listening on port %d", self._port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def wait_for_callback(self, timeout: float = 300.0) -> tuple[str, str | None]:
        """Block until the browser redirect delivers the authorization code.

        Returns (code, state). Raises asyncio.TimeoutError if not received within timeout.
        """
        if self._result is None:
            raise RuntimeError("CallbackServer not started — call start() first")
        return await asyncio.wait_for(asyncio.shield(self._result), timeout=timeout)

    async def _handle_request(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            raw = await reader.read(4096)
            request_line = raw.decode(errors="replace").split("\r\n")[0]
            if " " in request_line:
                path = request_line.split(" ")[1]
                params = parse_qs(urlparse(path).query)
                code = params.get("code", [""])[0]
                state = params.get("state", [None])[0]

                if code and self._result and not self._result.done():
                    self._result.set_result((code, state))
                    writer.write(_CALLBACK_HTML)
                else:
                    writer.write(_ERROR_HTML)
            else:
                writer.write(_ERROR_HTML)
        except Exception as exc:
            logger.debug("Callback server request error: %s", exc)
        finally:
            try:
                await writer.drain()
                writer.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_free_port() -> int:
    """Bind to port 0 to let the OS assign an available ephemeral port, then release it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_from_redirect_uri(uri: str) -> int | None:
    """Extract the port number from a redirect URI string."""
    try:
        return urlparse(str(uri)).port
    except Exception:
        return None


async def open_browser(url: str) -> None:
    """Redirect handler: log the authorization URL prominently and open the OS browser."""
    logger.warning(
        "\n%s\nMCP OAuth Authorization Required\nOpen this URL in your browser:\n  %s\n%s",
        "=" * 60,
        url,
        "=" * 60,
    )
    webbrowser.open(url)
