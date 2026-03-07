from fastapi import APIRouter, Request

from gateway.models.requests import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(request: Request):
    manager = request.app.state.session_manager
    return HealthResponse(status="ok", active_sessions=manager.active_count)
