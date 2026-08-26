"""OIDC/SSO auth seam (ADR-0002: Trust & access — provider not yet chosen).

[NEEDS CLARIFICATION]: identity provider unspecified. This dependency is a
placeholder seam so routes can declare `Depends(get_current_user)` now and get
real enforcement later without a signature change. It does NOT implement a
fake auth flow.
"""

from fastapi import HTTPException, status


class CurrentUser:
    """Placeholder principal shape. Replace fields once an OIDC provider is chosen."""

    def __init__(self, subject: str, roles: list[str]):
        self.subject = subject
        self.roles = roles


async def get_current_user() -> CurrentUser:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Auth not yet wired: OIDC/SSO provider not chosen (see ADR-0002 flagged gaps).",
    )
