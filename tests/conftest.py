from pathlib import Path

import httpx
import pytest

from app.db.base import Base
from app.config import Settings
from app.main import create_app
from app.services.bootstrap import ensure_bootstrap_admin


class FakeLiteLLMClient:
    def __init__(self) -> None:
        self.teams = []
        self.team_models = ["gpt-4o-mini", "claude-3-5-sonnet"]
        self.users = set()
        self.created_users = []
        self.generated = []
        self.deleted_keys = set()
        self.blocked = []
        self.unblocked = []
        self.deleted = []

    def get_team_info(self, team_id: str):
        from app.services.litellm import TeamInfo

        return TeamInfo(
            team_id=team_id,
            team_alias=f"{team_id}-alias",
            models=list(self.team_models),
            max_budget=25,
            rpm_limit=60,
            tpm_limit=10000,
            raw={},
        )

    def generate_key(self, **kwargs):
        from app.services.litellm import GeneratedKey

        key = f"sk-test-{len(self.generated) + 1:04d}-secret"
        self.generated.append({"key": key, **kwargs})
        return GeneratedKey(key=key, token_id=f"token-{len(self.generated)}", key_alias=kwargs["key_alias"], raw={})

    def get_user_info(self, user_id: str):
        from app.services.litellm import LiteLLMError, UserInfo

        if user_id not in self.users:
            raise LiteLLMError("missing user")
        return UserInfo(user_id=user_id, user_email=user_id, raw={})

    def create_user(self, **kwargs):
        from app.services.litellm import UserInfo

        self.users.add(kwargs["user_id"])
        self.created_users.append(kwargs)
        return UserInfo(user_id=kwargs["user_id"], user_email=kwargs["user_email"], raw={})

    def ensure_user(self, *, user_email: str, team_id: str, models: list[str]):
        try:
            return self.get_user_info(user_email)
        except Exception:
            return self.create_user(
                user_id=user_email,
                user_email=user_email,
                user_alias=user_email.split("@", 1)[0],
                team_id=team_id,
                models=models,
            )

    def get_key_info(self, key: str):
        from app.services.litellm import KeyInfo, LiteLLMError

        if key in self.deleted_keys:
            raise LiteLLMError("missing key")
        for generated in self.generated:
            if generated["key"] == key:
                return KeyInfo(
                    key=key,
                    key_alias=generated["key_alias"],
                    user_id=generated.get("user_id"),
                    team_id=generated.get("team_id"),
                    models=generated.get("models", []),
                    raw={},
                )
        raise RuntimeError("missing key")

    def list_keys(self, *, team_id: str):
        return [
            {
                "key": item["key"][:7] + "...secret",
                "key_alias": item["key_alias"],
                "user_id": item.get("user_id"),
                "team_id": item.get("team_id"),
                "models": item.get("models", []),
                "spend": 0,
            }
            for item in self.generated
            if item.get("team_id") == team_id and item["key"] not in self.deleted_keys
        ]

    def block_key(self, key: str) -> None:
        self.blocked.append(key)

    def unblock_key(self, key: str) -> None:
        self.unblocked.append(key)

    def delete_key(self, key: str) -> None:
        self.deleted_keys.add(key)
        self.deleted.append(key)


@pytest.fixture
def fake_litellm():
    return FakeLiteLLMClient()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client(tmp_path: Path, fake_litellm):
    db_path = tmp_path / "test.db"
    settings = Settings(
        DATABASE_URL=f"sqlite:///{db_path}",
        LITELLM_BASE_URL="http://litellm.test",
        LITELLM_MASTER_KEY="sk-master",
        APP_SECRET_KEY="test-app-secret",
        SESSION_SECRET="test-session-secret",
        BOOTSTRAP_ADMIN_EMAIL="admin@example.com",
        BOOTSTRAP_ADMIN_PASSWORD="admin-password",
        PUBLIC_BASE_URL="http://testserver",
        AUTO_CREATE_TABLES=False,
    )
    app = create_app(settings=settings, litellm_client=fake_litellm)
    Base.metadata.create_all(bind=app.state.SessionLocal.kw["bind"])
    with app.state.SessionLocal() as db:
        ensure_bootstrap_admin(db, settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        test_client.app = app
        yield test_client
