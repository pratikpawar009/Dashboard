"""Public export surface for `app.models` — Base + all 20 domain model classes.

Callers (migrations/env.py today; routers in later stories) import from
`app.models` without knowing the internal file grouping (D-02:
rollup.py / governance.py / ingestion.py, see docs/features/BED-01/DECISIONS.md;
roster.py added by ING-10, see docs/features/ING-10/DECISIONS.md D-01;
PersonaPrecedence added by AUTH-07, see docs/features/AUTH-07/DECISIONS.md D-05).
"""

from app.models.base import Base
from app.models.governance import (
    OrgConstitution,
    ProgramArtifact,
    ProgramGuardrail,
)
from app.models.ingestion import (
    IngestToken,
    PersonaConfig,
    PersonaPrecedence,
    SystemMetadata,
    UsageEvent,
    UserRole,
)
from app.models.rollup import (
    MauSeries,
    OrgSummaryRollup,
    ProgramCommands,
    ProgramMembers,
    ProgramReleases,
    ProgramSummary,
    ProgramTokenSeries,
    SessionSeries,
    TokenSeries,
    UserSessions,
)
from app.models.roster import ProgramRoster

__all__ = [
    "Base",
    "OrgConstitution",
    "ProgramArtifact",
    "ProgramGuardrail",
    "IngestToken",
    "PersonaConfig",
    "PersonaPrecedence",
    "SystemMetadata",
    "UsageEvent",
    "UserRole",
    "MauSeries",
    "OrgSummaryRollup",
    "ProgramCommands",
    "ProgramMembers",
    "ProgramReleases",
    "ProgramSummary",
    "ProgramTokenSeries",
    "SessionSeries",
    "TokenSeries",
    "UserSessions",
    "ProgramRoster",
]
