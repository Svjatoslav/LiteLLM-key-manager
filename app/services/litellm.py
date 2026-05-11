from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class LiteLLMError(RuntimeError):
    pass


@dataclass
class GeneratedKey:
    key: str
    token_id: str | None
    key_alias: str | None
    raw: dict[str, Any]


@dataclass
class KeyInfo:
    key: str | None
    key_alias: str | None
    user_id: str | None
    team_id: str | None
    models: list[str]
    raw: dict[str, Any]


@dataclass
class TeamInfo:
    team_id: str
    team_alias: str | None
    models: list[str]
    max_budget: float | None
    rpm_limit: int | None
    tpm_limit: int | None
    raw: dict[str, Any]


@dataclass
class UserInfo:
    user_id: str
    user_email: str | None
    raw: dict[str, Any]


class LiteLLMClient:
    def __init__(
        self,
        base_url: str,
        master_key: str,
        *,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.master_key = master_key
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.master_key}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._client.request(method, f"{self.base_url}{path}", headers=self._headers(), **kwargs)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            raise LiteLLMError(f"LiteLLM returned {exc.response.status_code}: {detail}") from exc
        except httpx.HTTPError as exc:
            raise LiteLLMError(f"LiteLLM request failed: {exc}") from exc

        if not response.content:
            return {}
        data = response.json()
        if not isinstance(data, dict):
            raise LiteLLMError("LiteLLM returned a non-object JSON response")
        return data

    @staticmethod
    def _first_present(*values: Any) -> Any:
        for value in values:
            if value is not None:
                return value
        return None

    def generate_key(
        self,
        *,
        team_id: str,
        models: list[str],
        key_alias: str,
        duration: str | None,
        metadata: dict[str, Any],
        max_budget: float | None,
        rpm_limit: int | None,
        tpm_limit: int | None,
        user_id: str | None = None,
    ) -> GeneratedKey:
        payload: dict[str, Any] = {
            "team_id": team_id,
            "models": models,
            "key_alias": key_alias,
            "metadata": metadata,
        }
        if duration:
            payload["duration"] = duration
        if max_budget is not None:
            payload["max_budget"] = max_budget
        if rpm_limit is not None:
            payload["rpm_limit"] = rpm_limit
        if tpm_limit is not None:
            payload["tpm_limit"] = tpm_limit
        if user_id:
            payload["user_id"] = user_id

        data = self._request("POST", "/key/generate", json=payload)
        key = data.get("key")
        if not key:
            raise LiteLLMError("LiteLLM did not return generated key")
        return GeneratedKey(
            key=str(key),
            token_id=data.get("token_id") or data.get("token"),
            key_alias=data.get("key_alias") or key_alias,
            raw=data,
        )

    def get_user_info(self, user_id: str) -> UserInfo:
        data = self._request("GET", "/user/info", params={"user_id": user_id})
        info = data.get("user_info") if isinstance(data.get("user_info"), dict) else data.get("info")
        if not isinstance(info, dict):
            info = data
        resolved_user_id = info.get("user_id") or data.get("user_id") or user_id
        return UserInfo(
            user_id=str(resolved_user_id),
            user_email=info.get("user_email") or info.get("email") or data.get("user_email"),
            raw=data,
        )

    def create_user(
        self,
        *,
        user_id: str,
        user_email: str,
        user_alias: str,
        team_id: str,
        models: list[str],
    ) -> UserInfo:
        payload: dict[str, Any] = {
            "user_id": user_id,
            "user_email": user_email,
            "user_alias": user_alias,
            "teams": [team_id],
            "models": models,
            "user_role": "internal_user",
            "send_invite_email": False,
            # Team leads create the actual employee key in a separate call.
            "auto_create_key": False,
        }
        data = self._request("POST", "/user/new", json=payload)
        resolved_user_id = data.get("user_id") or user_id
        return UserInfo(
            user_id=str(resolved_user_id),
            user_email=data.get("user_email") or user_email,
            raw=data,
        )

    def ensure_user(
        self,
        *,
        user_email: str,
        team_id: str,
        models: list[str],
    ) -> UserInfo:
        user_id = user_email.lower().strip()
        try:
            return self.get_user_info(user_id)
        except LiteLLMError:
            alias = user_id.split("@", 1)[0]
            return self.create_user(
                user_id=user_id,
                user_email=user_id,
                user_alias=alias,
                team_id=team_id,
                models=models,
            )

    def get_key_info(self, key: str) -> KeyInfo:
        data = self._request("GET", "/key/info", params={"key": key})
        info = data.get("info") if isinstance(data.get("info"), dict) else data
        models = info.get("models") or data.get("models") or []
        if not isinstance(models, list):
            models = []
        return KeyInfo(
            key=data.get("key") or info.get("key") or info.get("token"),
            key_alias=info.get("key_alias") or info.get("key_name") or data.get("key_alias"),
            user_id=info.get("user_id") or data.get("user_id"),
            team_id=info.get("team_id") or data.get("team_id"),
            models=[str(model) for model in models],
            raw=data,
        )

    def get_team_info(self, team_id: str) -> TeamInfo:
        try:
            data = self._request("GET", "/team/info", params={"team_id": team_id})
        except LiteLLMError:
            data = self._request("POST", "/team/info", json={"team_id": team_id})
        info = data.get("team_info") if isinstance(data.get("team_info"), dict) else data.get("info")
        if not isinstance(info, dict):
            info = data
        models = info.get("models") or info.get("access_groups") or data.get("models") or []
        if not isinstance(models, list):
            models = []
        resolved_team_id = info.get("team_id") or data.get("team_id") or team_id
        return TeamInfo(
            team_id=str(resolved_team_id),
            team_alias=info.get("team_alias") or info.get("team_name") or data.get("team_alias"),
            models=[str(model) for model in models],
            max_budget=self._first_present(info.get("max_budget"), data.get("max_budget")),
            rpm_limit=self._first_present(info.get("rpm_limit"), data.get("rpm_limit")),
            tpm_limit=self._first_present(info.get("tpm_limit"), data.get("tpm_limit")),
            raw=data,
        )

    def list_keys(self, *, team_id: str) -> list[dict[str, Any]]:
        data = self._request("GET", "/key/list", params={"team_id": team_id})
        keys = data.get("keys", [])
        if not isinstance(keys, list):
            raise LiteLLMError("LiteLLM returned invalid key list response")
        return [key for key in keys if isinstance(key, dict)]

    def block_key(self, key: str) -> None:
        self._request("POST", "/key/block", json={"key": key})

    def unblock_key(self, key: str) -> None:
        self._request("POST", "/key/unblock", json={"key": key})

    def delete_key(self, key: str) -> None:
        self._request("POST", "/key/delete", json={"keys": [key]})
