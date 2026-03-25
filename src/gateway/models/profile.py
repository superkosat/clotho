from pydantic import BaseModel, Field, field_validator


SUPPORTED_PROVIDERS = ["openai", "ollama", "anthropic"]


class ModelProfile(BaseModel):
    """Model provider configuration."""
    provider: str
    model: str
    base_url: str | None = None
    api_key: str | None = None
    context_window: int | None = None
    max_output_tokens: int | None = None

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        if v not in SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Provider must be one of {SUPPORTED_PROVIDERS}, got: {v}"
            )
        return v


class ModelProfileResponse(BaseModel):
    """Model profile with masked API key for responses."""
    provider: str
    model: str
    base_url: str | None = None
    api_key: str | None = None
    context_window: int | None = None
    max_output_tokens: int | None = None

    @classmethod
    def from_profile(cls, profile: ModelProfile) -> "ModelProfileResponse":
        masked_key = None
        if profile.api_key:
            if len(profile.api_key) > 4:
                masked_key = "..." + profile.api_key[-4:]
            else:
                masked_key = "***"

        return cls(
            provider=profile.provider,
            model=profile.model,
            base_url=profile.base_url,
            api_key=masked_key,
            context_window=profile.context_window,
            max_output_tokens=profile.max_output_tokens,
        )


class CreateProfileRequest(BaseModel):
    """Request to create a new profile."""
    name: str = Field(..., min_length=1, max_length=64)
    profile: ModelProfile


class UpdateProfileRequest(BaseModel):
    """Request to update existing profile."""
    profile: ModelProfile


class SetDefaultRequest(BaseModel):
    """Request to set default profile."""
    profile_name: str = Field(..., min_length=1)


class ProfileResponse(BaseModel):
    """Single profile response."""
    name: str
    profile: ModelProfileResponse


class ProfileListResponse(BaseModel):
    """List of all profiles."""
    default: str | None
    profiles: dict[str, ModelProfileResponse]


class DefaultProfileResponse(BaseModel):
    """Current default profile response."""
    default: str | None
