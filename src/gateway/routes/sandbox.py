from fastapi import APIRouter, Request
from pydantic import BaseModel

from sandbox.config import load_sandbox_config, save_sandbox_config

router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])


class SandboxStatusResponse(BaseModel):
    enabled: bool


class SetSandboxRequest(BaseModel):
    enabled: bool


@router.get("", response_model=SandboxStatusResponse)
def get_sandbox():
    cfg = load_sandbox_config()
    return SandboxStatusResponse(enabled=cfg.get("enabled", False))


@router.post("", response_model=SandboxStatusResponse)
def set_sandbox(body: SetSandboxRequest, request: Request):
    cfg = load_sandbox_config()
    cfg["enabled"] = body.enabled
    save_sandbox_config(cfg)

    # Apply sandbox change to all active sessions immediately
    manager = request.app.state.session_manager
    for state in manager._sessions.values():
        if body.enabled:
            state.controller._init_sandbox()
        else:
            state.controller._cleanup_sandbox()

    return SandboxStatusResponse(enabled=body.enabled)


@router.post("/build")
def build_sandbox(request: Request):
    """Build the sandbox Docker image and re-initialize active sessions."""
    from sandbox.build_image import build_sandbox_image
    success = build_sandbox_image()
    if not success:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail={"error": "SandboxBuildError", "message": "Sandbox image build failed. Check that Docker is running."})

    # Re-initialize all active sessions that have sandbox enabled
    manager = request.app.state.session_manager
    for state in manager._sessions.values():
        state.controller._init_sandbox()

    return {"built": True}
