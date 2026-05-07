from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditEvent, Team, User


def write_audit(
    db: Session,
    *,
    request: Request | None,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    team: Team | None = None,
    metadata: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            actor_user_id=actor.id if actor else None,
            team_id=team.id if team else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata_json=metadata or {},
            ip_address=request.client.host if request and request.client else None,
        )
    )

