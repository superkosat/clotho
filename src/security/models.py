from enum import StrEnum

from pydantic import BaseModel


class PermissionLevel(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PermissionMode(StrEnum):
    INTERACTIVE = "interactive"
    AUTONOMOUS = "autonomous"
    READONLY = "readonly"


MODE_DEFAULTS: dict[PermissionMode, dict[str, PermissionLevel]] = {
    PermissionMode.INTERACTIVE: {
        "__default__": PermissionLevel.ASK,
    },
    PermissionMode.AUTONOMOUS: {
        "__default__": PermissionLevel.ALLOW,
    },
    PermissionMode.READONLY: {
        "__default__": PermissionLevel.DENY,
        "read": PermissionLevel.ALLOW,
    },
}


class PermissionsConfig(BaseModel):
    mode: PermissionMode = PermissionMode.INTERACTIVE
    tool_overrides: dict[str, PermissionLevel] = {}
