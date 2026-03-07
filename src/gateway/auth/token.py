import hmac
import json
import os
import secrets
import stat
from pathlib import Path

CONFIG_DIR = Path.home() / ".clotho"
CONFIG_FILE = CONFIG_DIR / "config.json"


def generate_token() -> str:
    return "clo_" + secrets.token_hex(32)


def save_token(token: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    config = {}
    if CONFIG_FILE.exists():
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

    config["api_token"] = token
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")

    if os.name != "nt":
        CONFIG_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)


def load_token() -> str | None:
    if not CONFIG_FILE.exists():
        return None
    try:
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return config.get("api_token")
    except (json.JSONDecodeError, OSError):
        return None


def verify_token(provided: str) -> bool:
    stored = load_token()
    if stored is None:
        return False
    return hmac.compare_digest(stored, provided)
