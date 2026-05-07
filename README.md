# LiteLLM Team Keys

Small delegation service for free LiteLLM Proxy installs. Admins link existing LiteLLM teams, generate team-lead API keys, and team leads paste their `api-key`, see their team, and create/delete employee virtual keys inside that team.

## For Other LLMs

If you are another LLM reading this repo, this is the fastest map:

### Start here

- App bootstrap: [app/main.py](app/main.py)
- Request handlers and business flow: [app/web/routes.py](app/web/routes.py)
- LiteLLM API client: [app/services/litellm.py](app/services/litellm.py)
- DB models: [app/models.py](app/models.py)
- Settings and environment variables: [app/config.py](app/config.py)
- HTML templates: [templates/](templates/)
- Static CSS: [static/css/app.css](static/css/app.css)
- Tests: [tests/](tests/)

### What the service does

1. Admin logs in with bootstrap credentials.
2. Admin links an existing LiteLLM `team_id`.
3. Admin creates a team-lead API key for that team.
4. Team lead logs in with that API key.
5. Team lead refreshes team access from LiteLLM and creates employee keys.
6. If the employee user does not exist in LiteLLM, the service creates it first.

### Where to change things

- Admin UI and lead UI routes: [app/web/routes.py](app/web/routes.py)
- Lead dashboard template: [templates/team/lead_dashboard.html](templates/team/lead_dashboard.html)
- Admin dashboard template: [templates/admin/dashboard.html](templates/admin/dashboard.html)
- Login and invite screens: [templates/auth/](templates/auth/)
- LiteLLM request/response parsing: [app/services/litellm.py](app/services/litellm.py)
- Encryption / masking / password hashing: [app/core/security.py](app/core/security.py)
- Team / key / invite schema: [app/models.py](app/models.py)
- Access control helpers: [app/web/deps.py](app/web/deps.py)
- Bootstrap admin creation: [app/services/bootstrap.py](app/services/bootstrap.py)
- Audit log writer: [app/services/audit.py](app/services/audit.py)

### Important data objects

- `User`: local admin or invited human user.
- `Team`: local mirror of a linked LiteLLM team.
- `LeadApiKey`: the admin-issued key a team lead uses to enter the app.
- `EmployeeKey`: employee key created by the team lead.
- `Invite`: one-time invite flow for team membership.
- `AuditEvent`: local audit trail.
- `AdGroupMapping`: reserved for future AD/LDAP sync.

### Important flows in code

- Lead login with API key: `POST /login` in [app/web/routes.py](app/web/routes.py)
- Admin login: `POST /admin/login`
- Link existing LiteLLM team: `POST /admin/teams/link`
- Generate team-lead key: `POST /admin/teams/{team_id}/lead-keys`
- Team lead dashboard: `GET /team`
- Refresh team access from LiteLLM: `POST /team/refresh-models`
- Create employee key: `POST /team/keys`
- Delete employee key: `POST /team/keys/{key_id}/delete`
- Regenerate lead key: `POST /admin/lead-keys/{lead_key_id}/regenerate`

### LiteLLM integration notes

- The service talks to LiteLLM through [app/services/litellm.py](app/services/litellm.py).
- Team info is pulled from `/team/info`.
- Lead API keys are created with `/key/generate`.
- Employee users are ensured through `/user/info` and `/user/new`.
- Key deletion uses `/key/delete`, with block as fallback in some flows.
- The lead dashboard refreshes team access from LiteLLM on page load and before key creation.

### UI notes

- The lead dashboard is server-rendered Jinja, not SPA.
- The `Inherited access` block on the lead page shows the current LiteLLM access groups/models for the team.
- Deleted employee keys are hidden from the UI.
- Full keys are shown only once after creation.

### Configuration

Settings are defined in [app/config.py](app/config.py):

- `DATABASE_URL`
- `LITELLM_BASE_URL`
- `LITELLM_MASTER_KEY`
- `APP_SECRET_KEY`
- `SESSION_SECRET`
- `BOOTSTRAP_ADMIN_EMAIL`
- `BOOTSTRAP_ADMIN_PASSWORD`
- `PUBLIC_BASE_URL`
- `COOKIE_SECURE`
- `AUTO_CREATE_TABLES`

### Run locally

```bash
cp .env.example .env
docker compose up --build
```

Open `http://localhost:8000` for the team lead `api-key` screen.

Admins sign in at `http://localhost:8000/admin/login` with `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD`.

If you change `BOOTSTRAP_ADMIN_PASSWORD` after the admin user already exists, reset the stored hash:

```bash
docker compose exec litellm-keys python -m app.cli reset-admin-password
```

## Workflow

1. Admin creates or already has a team in LiteLLM.
2. Admin links that existing LiteLLM `team_id` in this service. The service reads the team's available LiteLLM models/access groups and limits from `/team/info`.
3. Admin generates a team lead API key for that linked team and sets the lead's LiteLLM `user_id`.
4. The lead opens `/login`, pastes the issued `api-key`, and sees the team plus available access groups.
5. The lead creates employee keys by entering the recipient email and selecting purpose `Coding` or `lagnflow`; the key inherits all current LiteLLM access groups available to the team.
6. If that email is not present as a LiteLLM user, the service creates it and makes that user the owner of the generated key.

Team lead keys can be regenerated from the admin UI. Regeneration deletes the old LiteLLM key when possible, falls back to blocking it, and shows the new key once.

The team lead UI refreshes the linked LiteLLM team's access groups from `/team/info` when opened and before key creation, so changes made in LiteLLM are picked up without re-linking the team manually.

## Security model

Full LiteLLM lead and employee keys are shown once in the UI. They are stored encrypted because documented LiteLLM management endpoints require the raw key for delete/block workflows. Templates, audit rows, and normal key lists only show masked keys.

## Active Directory

AD is intentionally outside v1. The schema includes `ad_group_mappings`, and `app.services.identity.IdentityProvider` is the integration point for a future LDAP/LDAPS sync.
