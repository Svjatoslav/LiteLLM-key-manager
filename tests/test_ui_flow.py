import re

import pytest
from sqlalchemy import select

from app.core.security import decrypt_secret
from app.models import EmployeeKey, LeadApiKey, Team


async def login_admin(client):
    response = await client.post(
        "/admin/login",
        data={"email": "admin@example.com", "password": "admin-password"},
        follow_redirects=False,
    )
    assert response.status_code == 303
@pytest.mark.anyio
async def test_admin_generates_lead_api_key_and_lead_creates_employee_key(client, fake_litellm):
    await login_admin(client)

    response = await client.get("/admin")
    assert "Link existing LiteLLM team" in response.text
    assert "Create team in LiteLLM" not in response.text

    response = await client.post(
        "/admin/teams/link",
        data={
            "litellm_team_id": "existing-platform-team",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    with client.app.state.SessionLocal() as db:
        team = db.scalar(select(Team).where(Team.slug == "existing-platform-team"))
        assert team is not None
        assert team.name == "existing-platform-team-alias"
        assert team.litellm_team_id == "existing-platform-team"
        assert team.models == ["gpt-4o-mini", "claude-3-5-sonnet"]
        assert team.max_budget == 25
        assert team.rpm_limit == 60
        assert team.tpm_limit == 10000
        team_id = team.id

    response = await client.post(
        "/admin/teams/link",
        data={
            "litellm_team_id": "existing-platform-team",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with client.app.state.SessionLocal() as db:
        teams = db.scalars(select(Team).where(Team.litellm_team_id == "existing-platform-team")).all()
        assert len(teams) == 1
        assert teams[0].id == team_id
        assert teams[0].name == "existing-platform-team-alias"

    response = await client.post(
        f"/admin/teams/{team_id}/lead-keys",
        data={"lead_email": "lead@example.com"},
    )
    assert response.status_code == 200
    lead_api_key = re.search(r"sk-test-0001-secret", response.text).group(0)
    assert fake_litellm.generated[0]["team_id"] == "existing-platform-team"
    assert fake_litellm.generated[0]["user_id"] == "lead@example.com"

    await client.post("/logout")
    response = await client.post(
        "/login",
        data={"api_key": lead_api_key},
        follow_redirects=False,
    )
    assert response.status_code == 303

    response = await client.post(
        "/team/keys",
        data={
            "key_type": "Coding",
            "employee_email": "ivan.petrov@example.com",
            "duration": "30d",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    response = await client.get("/team")
    assert "sk-test-0002-secret" in response.text

    response = await client.get("/team")
    assert "sk-test-0002-secret" not in response.text
    assert "sk-test...secret" in response.text

    with client.app.state.SessionLocal() as db:
        lead_key = db.scalar(select(LeadApiKey).where(LeadApiKey.lead_email == "lead@example.com"))
        key = db.scalar(select(EmployeeKey).where(EmployeeKey.key_type == "Coding"))
        assert lead_key is not None
        assert lead_key.litellm_user_id == "lead@example.com"
        assert key is not None
        assert key.owner_name == "ivan.petrov"
        assert key.owner_email == "ivan.petrov@example.com"
        assert key.key_alias.startswith("Coding-existing-platform-team-ivan-petrov-")
        assert key.models_snapshot == ["gpt-4o-mini", "claude-3-5-sonnet"]
        assert decrypt_secret(key.encrypted_key, client.app.state.settings.app_secret_key) == "sk-test-0002-secret"
        assert fake_litellm.created_users == [
            {
                "user_id": "lead@example.com",
                "user_email": "lead@example.com",
                "user_alias": "lead",
                "team_id": "existing-platform-team",
                "models": ["gpt-4o-mini", "claude-3-5-sonnet"],
            },
            {
                "user_id": "ivan.petrov@example.com",
                "user_email": "ivan.petrov@example.com",
                "user_alias": "ivan.petrov",
                "team_id": "existing-platform-team",
                "models": ["gpt-4o-mini", "claude-3-5-sonnet"],
            }
        ]
        assert fake_litellm.generated[1]["user_id"] == "ivan.petrov@example.com"

    fake_litellm.team_models = ["claude-3-5-sonnet"]
    response = await client.post("/team/refresh-models", follow_redirects=False)
    assert response.status_code == 303
    response = await client.get("/team")
    assert response.status_code == 200
    assert "Models list updated from LiteLLM" in response.text
    assert "Inherited access" in response.text
    assert "claude-3-5-sonnet" in response.text

    response = await client.post(
        "/team/keys",
        data={
            "key_type": "lagnflow",
            "employee_email": "petr.sidorov@example.com",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert fake_litellm.generated[-1]["models"] == ["claude-3-5-sonnet"]

    response = await client.post(f"/team/keys/{key.id}/delete", follow_redirects=False)
    assert response.status_code == 303
    assert fake_litellm.deleted == ["sk-test-0002-secret"]
    response = await client.get("/team")
    assert "Coding-existing-platform-team-ivan-petrov-" not in response.text
    assert "sk-test-0002-secret" not in response.text

    await client.post("/logout")
    await login_admin(client)
    response = await client.post(f"/admin/lead-keys/{lead_key.id}/regenerate")
    assert response.status_code == 200
    assert "sk-test-0004-secret" in response.text
    assert "sk-test-0001-secret" in fake_litellm.deleted


@pytest.mark.anyio
async def test_lead_dashboard_hides_key_deleted_directly_in_litellm(client, fake_litellm):
    await login_admin(client)

    await client.post(
        "/admin/teams/link",
        data={
            "litellm_team_id": "existing-platform-team",
        },
        follow_redirects=False,
    )

    with client.app.state.SessionLocal() as db:
        team = db.scalar(select(Team).where(Team.litellm_team_id == "existing-platform-team"))
        team_id = team.id

    response = await client.post(
        f"/admin/teams/{team_id}/lead-keys",
        data={"lead_email": "lead@example.com"},
    )
    lead_api_key = re.search(r"sk-test-0001-secret", response.text).group(0)

    await client.post("/logout")
    await client.post("/login", data={"api_key": lead_api_key}, follow_redirects=False)
    await client.post(
        "/team/keys",
        data={
            "key_type": "Coding",
            "employee_email": "ivan.petrov@example.com",
        },
        follow_redirects=False,
    )

    with client.app.state.SessionLocal() as db:
        key = db.scalar(select(EmployeeKey).where(EmployeeKey.owner_email == "ivan.petrov@example.com"))
        assert key is not None
        key_alias = key.key_alias

    fake_litellm.deleted_keys.add("sk-test-0002-secret")
    await client.get("/team")
    response = await client.get("/team")
    assert response.status_code == 200
    assert key_alias not in response.text

    with client.app.state.SessionLocal() as db:
        key = db.scalar(select(EmployeeKey).where(EmployeeKey.owner_email == "ivan.petrov@example.com"))
        assert key is not None
        assert key.status.value == "deleted"


@pytest.mark.anyio
async def test_lead_api_key_is_bound_to_one_team(client, fake_litellm):
    await login_admin(client)
    for slug in ["alpha", "beta"]:
        await client.post(
            "/admin/teams/link",
            data={
                "litellm_team_id": f"existing-{slug}",
            },
            follow_redirects=False,
        )

    with client.app.state.SessionLocal() as db:
        alpha = db.scalar(select(Team).where(Team.litellm_team_id == "existing-alpha"))
        beta = db.scalar(select(Team).where(Team.litellm_team_id == "existing-beta"))

    response = await client.post(
        f"/admin/teams/{alpha.id}/lead-keys",
        data={"lead_email": "lead2@example.com"},
    )
    lead_api_key = re.search(r"sk-test-0001-secret", response.text).group(0)
    await client.post("/logout")
    await client.post("/login", data={"api_key": lead_api_key}, follow_redirects=False)

    response = await client.get(f"/teams/{beta.id}")
    assert response.status_code == 303
