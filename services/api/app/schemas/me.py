"""Response schema for GET /api/me (AUTH-07-AC-1, `session-identity-api`, api.md).

`MeResponse` is the sealed `session-identity-api` envelope -- exactly `name` and
`persona`, nothing else. `extra="forbid"` makes the exact-two-field contract a
runtime guarantee, not just a convention: no additional field (e.g. `email`,
`groups`, `programs`, `jobTitle`) can ever leak onto the wire by accident.
"""

from pydantic import BaseModel, ConfigDict, Field


class MeResponse(BaseModel):
    """Session identity: display name + resolved persona (AUTH-07-AC-1).

    `name` is the verified token's OIDC profile-claim fallback chain
    (`CurrentUser.name`, AC-2) -- `None` when no profile claim is present
    (e.g. a `/auth/dev-bypass` token), never a fabricated placeholder. `persona`
    is `persona-resolver.resolve(role)`'s output verbatim (AC-3) -- never
    hardcoded by the route and never defaulted; a resolution failure raises
    before a response model is ever constructed (AC-4).
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(..., description="Display name, or None with no profile claims")
    persona: str = Field(..., description="persona-resolver.resolve(role)'s output, verbatim")
