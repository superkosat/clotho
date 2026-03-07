"""REST API endpoints for model profile management."""

from fastapi import APIRouter, HTTPException

from exceptions.config import ProfileNotFoundError
from gateway.models.profile import (
    CreateProfileRequest,
    UpdateProfileRequest,
    SetDefaultRequest,
    ProfileResponse,
    ProfileListResponse,
    DefaultProfileResponse,
    ModelProfileResponse,
)
from gateway.services.profile_service import ProfileService

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


@router.post("", status_code=201)
def create_profile(body: CreateProfileRequest) -> ProfileResponse:
    """Create a new model profile."""
    try:
        ProfileService.create_profile(body.name, body.profile)
        masked_profile = ModelProfileResponse.from_profile(body.profile)
        return ProfileResponse(name=body.name, profile=masked_profile)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("")
def list_profiles() -> ProfileListResponse:
    """List all model profiles."""
    return ProfileService.get_all()


@router.get("/{name}")
def get_profile(name: str) -> ProfileResponse:
    """Get a specific model profile by name."""
    try:
        profile = ProfileService.get_profile(name)
        masked_profile = ModelProfileResponse.from_profile(profile)
        return ProfileResponse(name=name, profile=masked_profile)
    except ProfileNotFoundError:
        raise HTTPException(status_code=404, detail={"error": "ProfileNotFoundError", "message": f"Profile '{name}' not found. Use /profiles to list available profiles."})


@router.put("/{name}")
def update_profile(name: str, body: UpdateProfileRequest) -> ProfileResponse:
    """Update an existing model profile."""
    try:
        ProfileService.update_profile(name, body.profile)
        masked_profile = ModelProfileResponse.from_profile(body.profile)
        return ProfileResponse(name=name, profile=masked_profile)
    except ProfileNotFoundError:
        raise HTTPException(status_code=404, detail={"error": "ProfileNotFoundError", "message": f"Profile '{name}' not found. Use /profiles to list available profiles."})


@router.delete("/{name}", status_code=204)
def delete_profile(name: str) -> None:
    """Delete a model profile."""
    try:
        ProfileService.delete_profile(name)
    except ProfileNotFoundError:
        raise HTTPException(status_code=404, detail={"error": "ProfileNotFoundError", "message": f"Profile '{name}' not found. Use /profiles to list available profiles."})
    except ValueError as e:
        # Default profile deletion error
        raise HTTPException(status_code=400, detail={"error": "ServiceException", "message": str(e)})


@router.get("/default/current")
def get_default_profile() -> DefaultProfileResponse:
    """Get the current default profile name."""
    default = ProfileService.get_default()
    return DefaultProfileResponse(default=default)


@router.post("/default/set")
def set_default_profile(body: SetDefaultRequest) -> DefaultProfileResponse:
    """Set the default model profile."""
    try:
        ProfileService.set_default(body.profile_name)
        return DefaultProfileResponse(default=body.profile_name)
    except ProfileNotFoundError:
        raise HTTPException(status_code=404, detail={"error": "ProfileNotFoundError", "message": f"Profile '{body.profile_name}' not found. Use /profiles to list available profiles."})
