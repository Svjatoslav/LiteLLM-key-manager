from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.security import decrypt_secret, encrypt_secret, hash_password, hash_token, mask_key, verify_password
from app.models import EmployeeKey, Invite, KeyStatus, LeadApiKey, Team, TeamMember, User, new_id, utcnow
from app.services.audit import write_audit
from app.services.litellm import LiteLLMClient, LiteLLMError
from app.web.deps import can_access_team, current_user, require_admin


router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _db(request: Request) -> Session:
    session_local = request.app.state.SessionLocal
    return session_local()


def _client(request: Request) -> LiteLLMClient:
    return request.app.state.litellm_client


def _settings(request: Request):
    return request.app.state.settings


def _models(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _int_or_none(value: str | None) -> int | None:
    if value is None or value.strip() == "":
        return None
    return int(value)


def _float_or_none(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    return float(value)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", value.lower().strip()).strip("-")
    if not slug:
        raise ValueError("slug is required")
    return slug


def _team_slug(name: str, litellm_team_id: str) -> str:
    try:
        return _slug(name)
    except ValueError:
        return _slug(litellm_team_id)


KEY_TYPES = ("Coding", "lagnflow")


def _key_alias(team: Team, key_type: str, owner: str) -> str:
    normalized_type = re.sub(r"[^A-Za-z0-9-]+", "-", key_type).strip("-")
    normalized_owner = re.sub(r"[^a-z0-9-]+", "-", owner.lower()).strip("-")
    return f"{normalized_type}-{team.slug}-{normalized_owner}-{uuid.uuid4().hex[:8]}"


def _email_local_part(email: str) -> str:
    normalized = email.lower().strip()
    if "@" not in normalized:
        raise HTTPException(status_code=400, detail="Employee email must contain @")
    local_part = normalized.split("@", 1)[0].strip()
    if not local_part:
        raise HTTPException(status_code=400, detail="Employee email local part is required")
    return local_part


def _remote_keys(request: Request, team: Team) -> list[dict]:
    try:
        return _client(request).list_keys(team_id=team.litellm_team_id)
    except LiteLLMError:
        return []


def _template(request: Request, name: str, context: dict, status_code: int = 200) -> HTMLResponse:
    base = {"request": request, "current_user": context.get("current_user")}
    base.update(context)
    return templates.TemplateResponse(request, name, base, status_code=status_code)


def _is_past(value: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value < utcnow()


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def _get_current(request: Request, db: Session) -> User:
    return current_user(request, db)


def _get_current_lead_key(request: Request, db: Session) -> LeadApiKey:
    lead_key_id = request.session.get("lead_api_key_id")
    if not lead_key_id:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    lead_key = db.get(LeadApiKey, lead_key_id)
    if not lead_key or lead_key.status != KeyStatus.active:
        request.session.clear()
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return lead_key


def _available_models(lead_key: LeadApiKey, team: Team) -> list[str]:
    return list(lead_key.models_snapshot or team.models)


def _refresh_team_from_litellm(request: Request, team: Team, lead_key: LeadApiKey | None = None) -> None:
    team_info = _client(request).get_team_info(team.litellm_team_id)
    if not team_info.models:
        raise LiteLLMError("LiteLLM team has no models/access groups available")
    team.models = team_info.models
    team.max_budget = team_info.max_budget
    team.rpm_limit = team_info.rpm_limit
    team.tpm_limit = team_info.tpm_limit
    if lead_key:
        allowed = [model for model in (lead_key.models_snapshot or []) if model in team_info.models]
        lead_key.models_snapshot = allowed or list(team_info.models)


def _visible_employee_keys_query(team_id: str):
    return (
        select(EmployeeKey)
        .where(EmployeeKey.team_id == team_id, EmployeeKey.status != KeyStatus.deleted)
        .order_by(EmployeeKey.created_at.desc())
    )


def _sync_deleted_employee_keys(request: Request, db: Session, team: Team) -> bool:
    changed = False
    keys = db.scalars(
        select(EmployeeKey).where(EmployeeKey.team_id == team.id, EmployeeKey.status != KeyStatus.deleted)
    ).all()
    if not keys:
        return False

    client = _client(request)
    app_secret_key = _settings(request).app_secret_key
    for key in keys:
        raw_key = decrypt_secret(key.encrypted_key, app_secret_key)
        try:
            info = client.get_key_info(raw_key)
        except LiteLLMError:
            key.status = KeyStatus.deleted
            changed = True
            continue
        if info.team_id and info.team_id != team.litellm_team_id:
            key.status = KeyStatus.deleted
            changed = True
    return changed


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> RedirectResponse:
    if request.session.get("lead_api_key_id"):
        return _redirect("/team")
    if request.session.get("user_id"):
        return _redirect("/admin" if request.session.get("is_admin") else "/teams")
    return _redirect("/login")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return _template(request, "auth/lead_login.html", {"current_user": None})


@router.post("/login")
async def lead_login(request: Request, api_key: str = Form(...)):
    raw_key = api_key.strip()
    with _db(request) as db:
        lead_key = db.scalar(
            select(LeadApiKey).options(joinedload(LeadApiKey.team)).where(LeadApiKey.token_hash == hash_token(raw_key))
        )
        if not lead_key or lead_key.status != KeyStatus.active:
            return _template(
                request,
                "auth/lead_login.html",
                {"current_user": None, "error": "Invalid or disabled api-key"},
                status_code=401,
            )
        try:
            info = _client(request).get_key_info(raw_key)
        except LiteLLMError as exc:
            return _template(
                request,
                "auth/lead_login.html",
                {"current_user": None, "error": f"LiteLLM rejected this api-key: {exc}"},
                status_code=401,
            )
        if info.team_id and info.team_id != lead_key.team.litellm_team_id:
            return _template(
                request,
                "auth/lead_login.html",
                {"current_user": None, "error": "api-key is not attached to the expected LiteLLM team"},
                status_code=403,
            )
        if info.models:
            lead_key.models_snapshot = [model for model in info.models if model in lead_key.team.models] or info.models
        if info.user_id:
            lead_key.litellm_user_id = info.user_id
        write_audit(
            db,
            request=request,
            actor=None,
            action="lead_api_key.login",
            entity_type="lead_api_key",
            entity_id=lead_key.id,
            team=lead_key.team,
            metadata={"lead_email": lead_key.lead_email},
        )
        db.commit()
        request.session.clear()
        request.session["lead_api_key_id"] = lead_key.id
        return _redirect("/team")


@router.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request) -> HTMLResponse:
    return _template(request, "auth/admin_login.html", {"current_user": None})


@router.post("/admin/login")
async def admin_login(request: Request, email: str = Form(...), password: str = Form(...)):
    with _db(request) as db:
        user = db.scalar(select(User).where(User.email == email.lower().strip()))
        if not user or not verify_password(password, user.password_hash):
            return _template(
                request,
                "auth/admin_login.html",
                {"current_user": None, "error": "Invalid email or password"},
                status_code=401,
            )
        request.session["user_id"] = user.id
        request.session["is_admin"] = user.is_admin
        write_audit(db, request=request, actor=user, action="auth.login", entity_type="user", entity_id=user.id)
        db.commit()
        return _redirect("/admin" if user.is_admin else "/teams")


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return _redirect("/login")


@router.get("/invites/{token}", response_class=HTMLResponse)
async def invite_page(request: Request, token: str) -> HTMLResponse:
    with _db(request) as db:
        invite = db.scalar(
            select(Invite).options(joinedload(Invite.team)).where(Invite.token_hash == hash_token(token))
        )
        if not invite or invite.accepted_at or _is_past(invite.expires_at):
            return _template(request, "auth/invite_invalid.html", {"current_user": None}, status_code=404)
        return _template(request, "auth/accept_invite.html", {"current_user": None, "invite": invite, "token": token})


@router.post("/invites/{token}")
async def accept_invite(request: Request, token: str, password: str = Form(...), password_confirm: str = Form(...)):
    if password != password_confirm or len(password) < 8:
        with _db(request) as db:
            invite = db.scalar(
                select(Invite).options(joinedload(Invite.team)).where(Invite.token_hash == hash_token(token))
            )
            return _template(
                request,
                "auth/accept_invite.html",
                {
                    "current_user": None,
                    "invite": invite,
                    "token": token,
                    "error": "Password must be at least 8 characters and match confirmation",
                },
                status_code=400,
            )

    with _db(request) as db:
        invite = db.scalar(
            select(Invite).options(joinedload(Invite.team)).where(Invite.token_hash == hash_token(token))
        )
        if not invite or invite.accepted_at or _is_past(invite.expires_at):
            return _template(request, "auth/invite_invalid.html", {"current_user": None}, status_code=404)

        user = db.scalar(select(User).where(User.email == invite.email.lower()))
        if not user:
            user = User(email=invite.email.lower(), password_hash=hash_password(password), is_admin=False)
            db.add(user)
            db.flush()
        else:
            user.password_hash = hash_password(password)

        membership = db.scalar(select(TeamMember).where(TeamMember.team_id == invite.team_id, TeamMember.user_id == user.id))
        if not membership:
            db.add(TeamMember(team_id=invite.team_id, user_id=user.id))
        invite.accepted_at = utcnow()
        write_audit(
            db,
            request=request,
            actor=user,
            action="invite.accept",
            entity_type="invite",
            entity_id=invite.id,
            team=invite.team,
        )
        db.commit()
        request.session["user_id"] = user.id
        request.session["is_admin"] = user.is_admin
        return _redirect(f"/teams/{invite.team_id}")


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request) -> HTMLResponse:
    with _db(request) as db:
        user = _get_current(request, db)
        require_admin(user)
        teams = db.scalars(select(Team).options(selectinload(Team.lead_api_keys)).order_by(Team.created_at.desc())).all()
        return _template(request, "admin/dashboard.html", {"current_user": user, "teams": teams})


@router.post("/admin/teams/link")
async def link_existing_team(
    request: Request,
    litellm_team_id: str = Form(...),
):
    with _db(request) as db:
        user = _get_current(request, db)
        require_admin(user)

        try:
            team_info = _client(request).get_team_info(litellm_team_id.strip())
            if not team_info.models:
                raise LiteLLMError("LiteLLM team has no models/access groups available")
            resolved_name = (team_info.team_alias or team_info.team_id).strip()
            normalized_slug = _team_slug(team_info.team_id, team_info.team_id)
            team = db.scalar(select(Team).where(Team.litellm_team_id == team_info.team_id))
            if team:
                team.name = resolved_name
                team.models = team_info.models
                team.max_budget = team_info.max_budget
                team.rpm_limit = team_info.rpm_limit
                team.tpm_limit = team_info.tpm_limit
                action = "team.refresh"
            else:
                team = Team(
                    name=resolved_name,
                    slug=normalized_slug,
                    litellm_team_id=team_info.team_id,
                    models=team_info.models,
                    max_budget=team_info.max_budget,
                    rpm_limit=team_info.rpm_limit,
                    tpm_limit=team_info.tpm_limit,
                )
                db.add(team)
                action = "team.link"
            db.flush()
            write_audit(db, request=request, actor=user, action=action, entity_type="team", entity_id=team.id, team=team)
            db.commit()
        except (IntegrityError, ValueError, LiteLLMError) as exc:
            db.rollback()
            teams = db.scalars(select(Team).options(selectinload(Team.lead_api_keys)).order_by(Team.created_at.desc())).all()
            return _template(request, "admin/dashboard.html", {"current_user": user, "teams": teams, "error": str(exc)}, 400)
        return _redirect("/admin")


@router.post("/admin/teams/{team_id}/lead-keys", response_class=HTMLResponse)
async def create_lead_api_key(
    request: Request,
    team_id: str,
    lead_email: str = Form(...),
) -> HTMLResponse:
    with _db(request) as db:
        user = _get_current(request, db)
        require_admin(user)
        team = db.get(Team, team_id)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")

        service_key_id = new_id()
        normalized_lead_email = lead_email.lower().strip()
        alias = _key_alias(team, "teamlead", normalized_lead_email)
        try:
            lead_user = _client(request).ensure_user(
                user_email=normalized_lead_email,
                team_id=team.litellm_team_id,
                models=team.models,
            )
            generated = _client(request).generate_key(
                team_id=team.litellm_team_id,
                models=team.models,
                key_alias=alias,
                duration=None,
                metadata={
                    "service_key_id": service_key_id,
                    "service_role": "team_lead",
                    "team_slug": team.slug,
                    "lead_email": normalized_lead_email,
                    "created_by": user.email,
                },
                max_budget=team.max_budget,
                rpm_limit=team.rpm_limit,
                tpm_limit=team.tpm_limit,
                user_id=lead_user.user_id,
            )
            lead_key = LeadApiKey(
                id=service_key_id,
                team_id=team.id,
                lead_email=normalized_lead_email,
                litellm_user_id=lead_user.user_id,
                key_alias=generated.key_alias or alias,
                token_hash=hash_token(generated.key),
                encrypted_key=encrypt_secret(generated.key, _settings(request).app_secret_key),
                masked_key=mask_key(generated.key),
                litellm_token_id=generated.token_id,
                models_snapshot=list(team.models),
                created_by_user_id=user.id,
            )
            db.add(lead_key)
            db.flush()
            write_audit(
                db,
                request=request,
                actor=user,
                action="lead_api_key.create",
                entity_type="lead_api_key",
                entity_id=lead_key.id,
                team=team,
                metadata={"lead_email": lead_key.lead_email, "litellm_user_id": lead_key.litellm_user_id},
            )
            db.commit()
        except (IntegrityError, LiteLLMError) as exc:
            db.rollback()
            teams = db.scalars(select(Team).options(selectinload(Team.lead_api_keys)).order_by(Team.created_at.desc())).all()
            return _template(request, "admin/dashboard.html", {"current_user": user, "teams": teams, "error": str(exc)}, 400)

        return _template(
            request,
            "admin/lead_key_created.html",
            {"current_user": user, "team": team, "lead_key": lead_key, "api_key": generated.key},
        )


@router.post("/admin/lead-keys/{lead_key_id}/regenerate", response_class=HTMLResponse)
async def regenerate_lead_api_key(request: Request, lead_key_id: str) -> HTMLResponse:
    with _db(request) as db:
        user = _get_current(request, db)
        require_admin(user)
        lead_key = db.scalar(
            select(LeadApiKey).options(joinedload(LeadApiKey.team)).where(LeadApiKey.id == lead_key_id)
        )
        if not lead_key:
            raise HTTPException(status_code=404, detail="Lead api-key not found")
        team = lead_key.team

        old_raw_key = decrypt_secret(lead_key.encrypted_key, _settings(request).app_secret_key)
        try:
            _client(request).delete_key(old_raw_key)
        except LiteLLMError:
            _client(request).block_key(old_raw_key)

        alias = _key_alias(team, "teamlead", lead_key.lead_email)
        generated = _client(request).generate_key(
            team_id=team.litellm_team_id,
            models=list(lead_key.models_snapshot or team.models),
            key_alias=alias,
            duration=None,
            metadata={
                "service_key_id": lead_key.id,
                "service_role": "team_lead",
                "team_slug": team.slug,
                "lead_email": lead_key.lead_email,
                "created_by": user.email,
                "regenerated": True,
            },
            max_budget=team.max_budget,
            rpm_limit=team.rpm_limit,
            tpm_limit=team.tpm_limit,
            user_id=lead_key.litellm_user_id,
        )
        lead_key.key_alias = generated.key_alias or alias
        lead_key.token_hash = hash_token(generated.key)
        lead_key.encrypted_key = encrypt_secret(generated.key, _settings(request).app_secret_key)
        lead_key.masked_key = mask_key(generated.key)
        lead_key.litellm_token_id = generated.token_id
        lead_key.status = KeyStatus.active
        write_audit(
            db,
            request=request,
            actor=user,
            action="lead_api_key.regenerate",
            entity_type="lead_api_key",
            entity_id=lead_key.id,
            team=team,
            metadata={"lead_email": lead_key.lead_email, "litellm_user_id": lead_key.litellm_user_id},
        )
        db.commit()
        return _template(
            request,
            "admin/lead_key_created.html",
            {"current_user": user, "team": team, "lead_key": lead_key, "api_key": generated.key, "regenerated": True},
        )


@router.post("/admin/teams/{team_id}/invites", response_class=HTMLResponse)
async def create_invite(request: Request, team_id: str, email: str = Form(...), expires_days: int = Form(7)) -> HTMLResponse:
    with _db(request) as db:
        user = _get_current(request, db)
        require_admin(user)
        team = db.get(Team, team_id)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")

        token = make_token()
        invite = Invite(
            token_hash=hash_token(token),
            email=email.lower().strip(),
            team_id=team.id,
            created_by_user_id=user.id,
            expires_at=utcnow() + timedelta(days=expires_days),
        )
        db.add(invite)
        db.flush()
        write_audit(db, request=request, actor=user, action="invite.create", entity_type="invite", entity_id=invite.id, team=team)
        db.commit()
        invite_url = f"{_settings(request).public_base_url}/invites/{token}"
        return _template(request, "admin/invite_created.html", {"current_user": user, "team": team, "invite": invite, "invite_url": invite_url})


@router.get("/teams", response_class=HTMLResponse)
async def team_list(request: Request):
    with _db(request) as db:
        user = _get_current(request, db)
        if user.is_admin:
            teams = db.scalars(select(Team).order_by(Team.name)).all()
        else:
            teams = db.scalars(
                select(Team).join(TeamMember).where(TeamMember.user_id == user.id).order_by(Team.name)
            ).all()
        if len(teams) == 1:
            return _redirect(f"/teams/{teams[0].id}")
        return _template(request, "team/list.html", {"current_user": user, "teams": teams})


@router.get("/teams/{team_id}", response_class=HTMLResponse)
async def team_dashboard(request: Request, team_id: str) -> HTMLResponse:
    with _db(request) as db:
        user = _get_current(request, db)
        team = db.get(Team, team_id)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        if not can_access_team(db, user, team):
            raise HTTPException(status_code=403, detail="Team access denied")
        keys = db.scalars(_visible_employee_keys_query(team.id)).all()
        return _template(request, "team/dashboard.html", {"current_user": user, "team": team, "keys": keys})


@router.get("/team", response_class=HTMLResponse)
async def lead_team_dashboard(request: Request) -> HTMLResponse:
    with _db(request) as db:
        lead_key = _get_current_lead_key(request, db)
        team = db.get(Team, lead_key.team_id)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        try:
            _refresh_team_from_litellm(request, team, lead_key)
            _sync_deleted_employee_keys(request, db, team)
            db.commit()
        except LiteLLMError:
            db.rollback()
        keys = db.scalars(_visible_employee_keys_query(team.id)).all()
        new_key = request.session.pop("new_key", None)
        new_key_owner = request.session.pop("new_key_owner", None)
        refresh_message = request.session.pop("refresh_message", None)
        return _template(
            request,
            "team/lead_dashboard.html",
            {
                "current_user": None,
                "lead_key": lead_key,
                "team": team,
                "keys": keys,
                "remote_keys": _remote_keys(request, team),
                "available_models": _available_models(lead_key, team),
                "key_types": KEY_TYPES,
                "new_key": new_key,
                "new_key_owner": new_key_owner,
                "refresh_message": refresh_message,
            },
        )


@router.post("/team/refresh-models")
async def lead_refresh_models(request: Request) -> RedirectResponse:
    with _db(request) as db:
        lead_key = _get_current_lead_key(request, db)
        team = db.get(Team, lead_key.team_id)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        _refresh_team_from_litellm(request, team, lead_key)
        db.commit()
        request.session["refresh_message"] = "Models list updated from LiteLLM"
        return _redirect("/team")


@router.post("/team/keys", response_class=HTMLResponse)
async def lead_create_employee_key(
    request: Request,
    key_type: str = Form(...),
    employee_email: str = Form(...),
    duration: str = Form(""),
) -> RedirectResponse:
    if key_type not in KEY_TYPES:
        raise HTTPException(status_code=400, detail="Unknown key purpose")

    with _db(request) as db:
        lead_key = _get_current_lead_key(request, db)
        team = db.get(Team, lead_key.team_id)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        _refresh_team_from_litellm(request, team, lead_key)
        allowed_models = _available_models(lead_key, team)
        if not allowed_models:
            raise HTTPException(status_code=400, detail="LiteLLM team has no available models/access groups")
        selected_models = list(allowed_models)
        normalized_employee_email = employee_email.lower().strip()
        owner_login = _email_local_part(normalized_employee_email)
        employee_user = _client(request).ensure_user(
            user_email=normalized_employee_email,
            team_id=team.litellm_team_id,
            models=selected_models,
        )

        service_key_id = new_id()
        alias = _key_alias(team, key_type, owner_login)
        generated = _client(request).generate_key(
            team_id=team.litellm_team_id,
            models=selected_models,
            key_alias=alias,
            duration=duration or None,
            metadata={
                "service_key_id": service_key_id,
                "service_role": "employee_key",
                "key_type": key_type,
                "team_slug": team.slug,
                "owner_login": owner_login,
                "owner_email": normalized_employee_email,
                "created_by_lead_email": lead_key.lead_email,
                "created_by_lead_key_id": lead_key.id,
            },
            max_budget=team.max_budget,
            rpm_limit=team.rpm_limit,
            tpm_limit=team.tpm_limit,
            user_id=employee_user.user_id,
        )
        employee_key = EmployeeKey(
            id=service_key_id,
            team_id=team.id,
            owner_email=normalized_employee_email,
            owner_name=owner_login,
            purpose=key_type,
            key_type=key_type,
            duration=duration or None,
            key_alias=generated.key_alias or alias,
            litellm_token_id=generated.token_id,
            encrypted_key=encrypt_secret(generated.key, _settings(request).app_secret_key),
            masked_key=mask_key(generated.key),
            models_snapshot=selected_models,
            limits_snapshot={"max_budget": team.max_budget, "rpm_limit": team.rpm_limit, "tpm_limit": team.tpm_limit},
            created_by_user_id=lead_key.created_by_user_id,
        )
        db.add(employee_key)
        db.flush()
        write_audit(
            db,
            request=request,
            actor=None,
            action="key.create_by_lead",
            entity_type="employee_key",
            entity_id=employee_key.id,
            team=team,
            metadata={
                "lead_email": lead_key.lead_email,
                "lead_key_id": lead_key.id,
                "key_type": key_type,
                "owner_login": owner_login,
                "owner_email": normalized_employee_email,
                "litellm_user_id": employee_user.user_id,
            },
        )
        db.commit()
        request.session["new_key"] = generated.key
        request.session["new_key_owner"] = normalized_employee_email
        return _redirect("/team")


@router.post("/team/keys/{key_id}/delete")
async def lead_delete_employee_key(request: Request, key_id: str) -> RedirectResponse:
    with _db(request) as db:
        lead_key = _get_current_lead_key(request, db)
        team = db.get(Team, lead_key.team_id)
        key = db.get(EmployeeKey, key_id)
        if not team or not key or key.team_id != team.id:
            raise HTTPException(status_code=404, detail="Key not found")
        if key.status == KeyStatus.deleted:
            return _redirect("/team")
        _client(request).delete_key(decrypt_secret(key.encrypted_key, _settings(request).app_secret_key))
        key.status = KeyStatus.deleted
        write_audit(
            db,
            request=request,
            actor=None,
            action="key.delete_by_lead",
            entity_type="employee_key",
            entity_id=key.id,
            team=team,
            metadata={"lead_email": lead_key.lead_email, "lead_key_id": lead_key.id},
        )
        db.commit()
        return _redirect("/team")


@router.post("/teams/{team_id}/keys", response_class=HTMLResponse)
async def create_employee_key(
    request: Request,
    team_id: str,
    owner_email: str = Form(...),
    owner_name: str = Form(...),
    purpose: str = Form(""),
    duration: str = Form(""),
) -> HTMLResponse:
    with _db(request) as db:
        user = _get_current(request, db)
        team = db.get(Team, team_id)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        if not can_access_team(db, user, team):
            raise HTTPException(status_code=403, detail="Team access denied")

        service_key_id = new_id()
        alias = _key_alias(team, "Coding", owner_email)
        generated = _client(request).generate_key(
            team_id=team.litellm_team_id,
            models=team.models,
            key_alias=alias,
            duration=duration or None,
            metadata={
                "service_key_id": service_key_id,
                "team_slug": team.slug,
                "owner_email": owner_email.lower().strip(),
                "created_by": user.email,
            },
            max_budget=team.max_budget,
            rpm_limit=team.rpm_limit,
            tpm_limit=team.tpm_limit,
        )
        employee_key = EmployeeKey(
            id=service_key_id,
            team_id=team.id,
            owner_email=owner_email.lower().strip(),
            owner_name=owner_name.strip(),
            purpose=purpose.strip(),
            key_type="Coding",
            duration=duration or None,
            key_alias=generated.key_alias or alias,
            litellm_token_id=generated.token_id,
            encrypted_key=encrypt_secret(generated.key, _settings(request).app_secret_key),
            masked_key=mask_key(generated.key),
            models_snapshot=list(team.models),
            limits_snapshot={"max_budget": team.max_budget, "rpm_limit": team.rpm_limit, "tpm_limit": team.tpm_limit},
            created_by_user_id=user.id,
        )
        db.add(employee_key)
        db.flush()
        write_audit(db, request=request, actor=user, action="key.create", entity_type="employee_key", entity_id=employee_key.id, team=team)
        db.commit()
        keys = db.scalars(_visible_employee_keys_query(team.id)).all()
        return _template(
            request,
            "team/dashboard.html",
            {"current_user": user, "team": team, "keys": keys, "new_key": generated.key, "new_key_owner": owner_email},
        )


def _load_key_for_action(db: Session, user: User, team_id: str, key_id: str) -> tuple[Team, EmployeeKey]:
    team = db.get(Team, team_id)
    key = db.get(EmployeeKey, key_id)
    if not team or not key or key.team_id != team.id:
        raise HTTPException(status_code=404, detail="Key not found")
    if not can_access_team(db, user, team):
        raise HTTPException(status_code=403, detail="Team access denied")
    return team, key


@router.post("/teams/{team_id}/keys/{key_id}/block")
async def block_employee_key(request: Request, team_id: str, key_id: str) -> RedirectResponse:
    with _db(request) as db:
        user = _get_current(request, db)
        team, key = _load_key_for_action(db, user, team_id, key_id)
        _client(request).block_key(decrypt_secret(key.encrypted_key, _settings(request).app_secret_key))
        key.status = KeyStatus.blocked
        write_audit(db, request=request, actor=user, action="key.block", entity_type="employee_key", entity_id=key.id, team=team)
        db.commit()
        return _redirect(f"/teams/{team.id}")


@router.post("/teams/{team_id}/keys/{key_id}/unblock")
async def unblock_employee_key(request: Request, team_id: str, key_id: str) -> RedirectResponse:
    with _db(request) as db:
        user = _get_current(request, db)
        team, key = _load_key_for_action(db, user, team_id, key_id)
        _client(request).unblock_key(decrypt_secret(key.encrypted_key, _settings(request).app_secret_key))
        key.status = KeyStatus.active
        write_audit(db, request=request, actor=user, action="key.unblock", entity_type="employee_key", entity_id=key.id, team=team)
        db.commit()
        return _redirect(f"/teams/{team.id}")


@router.post("/teams/{team_id}/keys/{key_id}/delete")
async def delete_employee_key(request: Request, team_id: str, key_id: str) -> RedirectResponse:
    with _db(request) as db:
        user = _get_current(request, db)
        team, key = _load_key_for_action(db, user, team_id, key_id)
        _client(request).delete_key(decrypt_secret(key.encrypted_key, _settings(request).app_secret_key))
        key.status = KeyStatus.deleted
        write_audit(db, request=request, actor=user, action="key.delete", entity_type="employee_key", entity_id=key.id, team=team)
        db.commit()
        return _redirect(f"/teams/{team.id}")


@router.post("/teams/{team_id}/keys/{key_id}/rotate", response_class=HTMLResponse)
async def rotate_employee_key(request: Request, team_id: str, key_id: str) -> HTMLResponse:
    with _db(request) as db:
        user = _get_current(request, db)
        team, old = _load_key_for_action(db, user, team_id, key_id)
        old_raw_key = decrypt_secret(old.encrypted_key, _settings(request).app_secret_key)
        _client(request).block_key(old_raw_key)
        _client(request).delete_key(old_raw_key)

        service_key_id = new_id()
        alias = _key_alias(team, old.key_type, old.owner_email)
        generated = _client(request).generate_key(
            team_id=team.litellm_team_id,
            models=team.models,
            key_alias=alias,
            duration=old.duration,
            metadata={
                "service_key_id": service_key_id,
                "team_slug": team.slug,
                "owner_email": old.owner_email,
                "created_by": user.email,
                "rotated_from_key_id": old.id,
            },
            max_budget=team.max_budget,
            rpm_limit=team.rpm_limit,
            tpm_limit=team.tpm_limit,
        )
        old.status = KeyStatus.deleted
        new_key = EmployeeKey(
            id=service_key_id,
            team_id=team.id,
            owner_email=old.owner_email,
            owner_name=old.owner_name,
            purpose=old.purpose,
            key_type=old.key_type,
            duration=old.duration,
            key_alias=generated.key_alias or alias,
            litellm_token_id=generated.token_id,
            encrypted_key=encrypt_secret(generated.key, _settings(request).app_secret_key),
            masked_key=mask_key(generated.key),
            models_snapshot=list(team.models),
            limits_snapshot={"max_budget": team.max_budget, "rpm_limit": team.rpm_limit, "tpm_limit": team.tpm_limit},
            created_by_user_id=user.id,
            rotated_from_key_id=old.id,
        )
        db.add(new_key)
        db.flush()
        write_audit(db, request=request, actor=user, action="key.rotate", entity_type="employee_key", entity_id=new_key.id, team=team)
        db.commit()
        keys = db.scalars(_visible_employee_keys_query(team.id)).all()
        return _template(
            request,
            "team/dashboard.html",
            {"current_user": user, "team": team, "keys": keys, "new_key": generated.key, "new_key_owner": old.owner_email},
        )
