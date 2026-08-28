from pydantic import BaseModel, Field


class TokenResponse(BaseModel):
    """Response shared by /auth/callback, /auth/refresh, /auth/dev-bypass (AUTH-01-FR-3/FR-7)."""

    access_token: str = Field(
        ..., description="Keycloak-issued access token, passed through unmodified"
    )
    refresh_token: str = Field(
        ..., description="Keycloak-issued refresh token, passed through unmodified"
    )
    expires_in: int = Field(
        ..., description="Access-token lifetime in seconds, realm-driven, never a constant"
    )


class DevBypassRequest(BaseModel):
    """Optional overrides for a dev-bypass sign-in (AUTH-01-FR-7)."""

    role: str | None = None
    email: str | None = None
    programs: list[str] | None = None
