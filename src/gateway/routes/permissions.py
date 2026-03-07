from fastapi import APIRouter, HTTPException

from gateway.models.requests import UpdatePermissionsRequest
from gateway.session import DEFAULT_TOOLS
from security.models import PermissionLevel, PermissionMode, PermissionsConfig
from security.permissions import load_permissions, save_permissions

router = APIRouter(prefix="/api/permissions", tags=["permissions"])

# Valid tool names for validation
VALID_TOOL_NAMES = {tool.name for tool in DEFAULT_TOOLS}


@router.get("")
def get_permissions():
    return load_permissions().model_dump()


@router.get("/tools")
def get_available_tools():
    """Return list of available tool names for validation."""
    return {"tools": sorted(VALID_TOOL_NAMES)}


@router.put("")
def update_permissions(body: UpdatePermissionsRequest):
    perms = load_permissions()

    if body.mode is not None:
        try:
            perms.mode = PermissionMode(body.mode)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid mode: {body.mode}. Must be one of: interactive, autonomous, readonly",
            )

    if body.tool_overrides is not None:
        validated = {}
        for tool_name, level_str in body.tool_overrides.items():
            # Validate tool name exists
            if tool_name not in VALID_TOOL_NAMES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid tool name '{tool_name}'. Must be one of: {', '.join(sorted(VALID_TOOL_NAMES))}",
                )
            # Validate permission level
            try:
                validated[tool_name] = PermissionLevel(level_str)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid permission level '{level_str}' for tool '{tool_name}'. Must be: allow, ask, deny",
                )
        perms.tool_overrides = validated

    save_permissions(perms)
    return perms.model_dump()
