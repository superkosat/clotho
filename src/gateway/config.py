import os
from dotenv import load_dotenv

load_dotenv()


class GatewaySettings:
    def __init__(self):
        self.host: str = os.getenv("CLOTHO_HOST", "0.0.0.0")
        self.port: int = int(os.getenv("CLOTHO_PORT", "8000"))
        self.cors_origins: list[str] = os.getenv("CLOTHO_CORS_ORIGINS", "*").split(",")
        self.approval_timeout_seconds: float = float(os.getenv("CLOTHO_APPROVAL_TIMEOUT", "300"))


settings = GatewaySettings()
