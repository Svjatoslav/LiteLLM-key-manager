import argparse

from sqlalchemy import select

from app.config import get_settings
from app.core.security import hash_password
from app.db.session import build_sessionmaker
from app.models import User


def reset_admin_password() -> None:
    settings = get_settings()
    session_local = build_sessionmaker(settings.database_url)
    email = settings.bootstrap_admin_email.lower().strip()
    with session_local() as db:
        user = db.scalar(select(User).where(User.email == email))
        if not user:
            user = User(email=email, is_admin=True)
            db.add(user)
            db.flush()
        user.password_hash = hash_password(settings.bootstrap_admin_password)
        user.is_admin = True
        db.commit()
    print(f"Reset admin password for {email}")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("reset-admin-password")
    args = parser.parse_args()

    if args.command == "reset-admin-password":
        reset_admin_password()


if __name__ == "__main__":
    main()
