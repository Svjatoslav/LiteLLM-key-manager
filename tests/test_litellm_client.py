import httpx
import pytest

from app.services.litellm import LiteLLMClient, LiteLLMError


def test_generate_key_for_existing_team_payload():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/key/generate":
            assert request.headers["authorization"] == "Bearer sk-master"
            payload = dict(__import__("json").loads(request.content))
            assert payload["team_id"] == "existing-team-123"
            assert payload["user_id"] == "lead-user"
            assert payload["metadata"]["owner_email"] == "dev@example.com"
            return httpx.Response(200, json={"key": "sk-live-secret", "token_id": "tok-1", "key_alias": payload["key_alias"]})
        return httpx.Response(404, json={"error": "missing"})

    client = LiteLLMClient("http://litellm.test", "sk-master", transport=httpx.MockTransport(handler))

    generated = client.generate_key(
        team_id="existing-team-123",
        models=["gpt-4o-mini"],
        key_alias="platform-dev",
        duration="30d",
        metadata={"owner_email": "dev@example.com"},
        max_budget=10,
        rpm_limit=60,
        tpm_limit=None,
        user_id="lead-user",
    )

    assert generated.key == "sk-live-secret"
    assert generated.token_id == "tok-1"
    assert [request.url.path for request in requests] == ["/key/generate"]


def test_get_team_info_reads_models_and_limits():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/team/info"
        assert request.url.params["team_id"] == "existing-team-123"
        return httpx.Response(
            200,
            json={
                "team_info": {
                    "team_id": "existing-team-123",
                    "team_alias": "Platform",
                    "models": ["coding-models", "langflow-models"],
                    "max_budget": 25,
                    "rpm_limit": 60,
                    "tpm_limit": 10000,
                }
            },
        )

    client = LiteLLMClient("http://litellm.test", "sk-master", transport=httpx.MockTransport(handler))

    team_info = client.get_team_info("existing-team-123")

    assert team_info.models == ["coding-models", "langflow-models"]
    assert team_info.max_budget == 25
    assert team_info.rpm_limit == 60
    assert team_info.tpm_limit == 10000


def test_ensure_user_creates_missing_user_with_team_and_models():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/user/info":
            return httpx.Response(404, json={"error": "missing"})
        if request.url.path == "/user/new":
            payload = dict(__import__("json").loads(request.content))
            assert payload["user_id"] == "ivan.petrov@example.com"
            assert payload["user_email"] == "ivan.petrov@example.com"
            assert payload["user_alias"] == "ivan.petrov"
            assert payload["teams"] == ["existing-team-123"]
            assert payload["models"] == ["coding-models"]
            assert payload["send_invite_email"] is False
            assert payload["auto_create_key"] is False
            return httpx.Response(200, json={"user_id": payload["user_id"], "user_email": payload["user_email"]})
        return httpx.Response(404, json={"error": "missing"})

    client = LiteLLMClient("http://litellm.test", "sk-master", transport=httpx.MockTransport(handler))

    user = client.ensure_user(
        user_email="ivan.petrov@example.com",
        team_id="existing-team-123",
        models=["coding-models"],
    )

    assert user.user_id == "ivan.petrov@example.com"
    assert [request.url.path for request in requests] == ["/user/info", "/user/new"]


def test_litellm_error_on_http_failure():
    client = LiteLLMClient(
        "http://litellm.test",
        "sk-master",
        transport=httpx.MockTransport(lambda request: httpx.Response(500, text="boom")),
    )

    with pytest.raises(LiteLLMError):
        client.block_key("sk-bad")
