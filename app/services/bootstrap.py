from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.security import hash_password
from app.models import User


def ensure_bootstrap_admin(db: Session, settings: Settings) -> User:
    email = settings.bootstrap_admin_email.lower().strip()
    user = db.scalar(select(User).where(User.email == email))
    if user:
        if not user.is_admin:
            user.is_admin = True
            db.commit()
        return user

    user = User(
        email=email,
        password_hash=hash_password(settings.bootstrap_admin_password),
        is_admin=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

