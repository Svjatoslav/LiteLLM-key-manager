from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Team, TeamMember, User


def redirect_exception(location: str) -> HTTPException:
    return HTTPException(status_code=303, headers={"Location": location})


def current_user(request: Request, db: Session) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise redirect_exception("/login")
    user = db.get(User, user_id)
    if not user or user.disabled_at is not None:
        request.session.clear()
        raise redirect_exception("/login")
    return user


def require_admin(user: User) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")


def can_access_team(db: Session, user: User, team: Team) -> bool:
    if user.is_admin:
        return True
    membership = db.scalar(
        select(TeamMember).where(TeamMember.team_id == team.id, TeamMember.user_id == user.id)
    )
    return membership is not None
