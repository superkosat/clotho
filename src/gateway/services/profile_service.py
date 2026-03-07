"""Service for managing model profiles."""

import json
from pathlib import Path

from exceptions.config import ProfileNotFoundError
from gateway.models.profile import (
    ModelProfile,
    ModelProfileResponse,
    ProfileListResponse,
)


class ProfileService:
    """Manages model profiles stored in ~/.clotho/profiles.json."""

    PROFILES_DIR = Path.home() / ".clotho"
    PROFILES_FILE = PROFILES_DIR / "profiles.json"

    @classmethod
    def _ensure_file_exists(cls) -> None:
        """Ensure profiles file exists with default structure."""
        cls.PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        if not cls.PROFILES_FILE.exists():
            cls.PROFILES_FILE.write_text(
                json.dumps({"default": None, "profiles": {}}, indent=2),
                encoding="utf-8"
            )

    @classmethod
    def _read_profiles(cls) -> dict:
        """Read profiles file."""
        cls._ensure_file_exists()
        try:
            return json.loads(cls.PROFILES_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Corrupted file, reset to default
            return {"default": None, "profiles": {}}

    @classmethod
    def _write_profiles(cls, data: dict) -> None:
        """Write profiles file."""
        cls.PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        cls.PROFILES_FILE.write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )

    @classmethod
    def get_all(cls) -> ProfileListResponse:
        """Get all profiles with masked API keys."""
        data = cls._read_profiles()
        profiles = data.get("profiles", {})

        # Convert to ModelProfile objects then mask
        masked_profiles = {}
        for name, profile_dict in profiles.items():
            profile = ModelProfile(**profile_dict)
            masked_profiles[name] = ModelProfileResponse.from_profile(profile)

        return ProfileListResponse(
            default=data.get("default"),
            profiles=masked_profiles,
        )

    @classmethod
    def get_profile(cls, name: str) -> ModelProfile:
        """Get a specific profile by name (with full API key).

        Raises:
            ProfileNotFoundError: If profile doesn't exist
        """
        data = cls._read_profiles()
        profiles = data.get("profiles", {})

        if name not in profiles:
            raise ProfileNotFoundError(name)

        return ModelProfile(**profiles[name])

    @classmethod
    def create_profile(cls, name: str, profile: ModelProfile) -> None:
        """Create a new profile.

        Raises:
            ValueError: If profile name already exists
        """
        data = cls._read_profiles()
        profiles = data.get("profiles", {})

        if name in profiles:
            raise ValueError(f"Profile '{name}' already exists")

        profiles[name] = profile.model_dump()
        data["profiles"] = profiles
        cls._write_profiles(data)

    @classmethod
    def update_profile(cls, name: str, profile: ModelProfile) -> None:
        """Update an existing profile.

        Raises:
            ProfileNotFoundError: If profile doesn't exist
        """
        data = cls._read_profiles()
        profiles = data.get("profiles", {})

        if name not in profiles:
            raise ProfileNotFoundError(name)

        profiles[name] = profile.model_dump()
        data["profiles"] = profiles
        cls._write_profiles(data)

    @classmethod
    def delete_profile(cls, name: str) -> None:
        """Delete a profile.

        Raises:
            ProfileNotFoundError: If profile doesn't exist
            ValueError: If trying to delete the default profile
        """
        data = cls._read_profiles()
        profiles = data.get("profiles", {})

        if name not in profiles:
            raise ProfileNotFoundError(name)

        # Don't allow deleting the default profile
        if data.get("default") == name:
            raise ValueError(
                f"Cannot delete default profile '{name}'. "
                "Set a different default first."
            )

        del profiles[name]
        data["profiles"] = profiles
        cls._write_profiles(data)

    @classmethod
    def get_default(cls) -> str | None:
        """Get the name of the default profile."""
        data = cls._read_profiles()
        return data.get("default")

    @classmethod
    def set_default(cls, name: str) -> None:
        """Set the default profile.

        Raises:
            ProfileNotFoundError: If profile doesn't exist
        """
        data = cls._read_profiles()
        profiles = data.get("profiles", {})

        if name not in profiles:
            raise ProfileNotFoundError(name)

        data["default"] = name
        cls._write_profiles(data)

    @classmethod
    def clear_default(cls) -> None:
        """Clear the default profile (set to None)."""
        data = cls._read_profiles()
        data["default"] = None
        cls._write_profiles(data)
