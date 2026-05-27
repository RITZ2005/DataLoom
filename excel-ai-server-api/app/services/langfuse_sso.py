from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import quote, urlencode

import httpx

from app.config import redis_client, _try_redis_connect
from app.utils.logging import logger

_LANGFUSE_ORIGIN = os.getenv("LANGFUSE_HOST", "http://localhost:3000").rstrip("/")

# Per-user Langfuse session cookies: email -> {cookie_name: cookie_value}
_user_langfuse_cookies: dict = {}

# One-time SSO keys: uuid -> (email, expiry_datetime, target_langfuse_url)
_sso_keys: dict = {}

def _get_redis():
    """Get Redis client, lazy-retrying connection if not available at startup."""
    import app.config as _cfg
    if _cfg.redis_client is not None:
        return _cfg.redis_client
    return _try_redis_connect()


def build_langfuse_project_url() -> str:
    langfuse_project = os.getenv("LANGFUSE_PROJECT_ID", "")
    if langfuse_project:
        return f"{_LANGFUSE_ORIGIN}/project/{langfuse_project}"
    return _LANGFUSE_ORIGIN


def build_langfuse_session_url(session_id: Optional[str]) -> str:
    sid = (session_id or "").strip()
    if not sid:
        return build_langfuse_project_url()
    escaped_sid = quote(sid, safe="")
    langfuse_project = os.getenv("LANGFUSE_PROJECT_ID", "")
    if langfuse_project:
        return f"{_LANGFUSE_ORIGIN}/project/{langfuse_project}/sessions/{escaped_sid}"
    return f"{_LANGFUSE_ORIGIN}/sessions/{escaped_sid}"


def build_langfuse_traces_url(session_id: Optional[str] = None) -> str:
    """Build Langfuse traces-list URL, optionally filtered by session."""
    langfuse_project = os.getenv("LANGFUSE_PROJECT_ID", "")
    base = (
        f"{_LANGFUSE_ORIGIN}/project/{langfuse_project}/traces"
        if langfuse_project
        else f"{_LANGFUSE_ORIGIN}/traces"
    )
    params = []
    if (session_id or "").strip():
        params.append(("sessionId", session_id.strip()))
    return f"{base}?{urlencode(params)}" if params else base


def build_langfuse_trace_url(trace_id: str) -> str:
    langfuse_project = os.getenv("LANGFUSE_PROJECT_ID", "")
    if langfuse_project:
        return f"{_LANGFUSE_ORIGIN}/project/{langfuse_project}/traces/{trace_id}"
    return f"{_LANGFUSE_ORIGIN}/traces/{trace_id}"


def save_langfuse_cookies_to_redis(email: str, cookies: dict) -> None:
    """Persist Langfuse cookies to Redis with 48h TTL."""
    rc = _get_redis()
    if not rc:
        return
    try:
        key = f"langfuse:cookies:{email}"
        rc.setex(key, 604800, json.dumps(cookies))  # 7-day TTL
        logger.debug("[Redis] Saved Langfuse cookies for %s", email)
    except Exception as e:
        logger.warning("[Redis] Failed to save cookies for %s: %s", email, e)


def load_langfuse_cookies_from_redis(email: str) -> dict:
    """Load Langfuse cookies from Redis."""
    rc = _get_redis()
    if not rc:
        return {}
    try:
        key = f"langfuse:cookies:{email}"
        data = rc.get(key)
        if data:
            logger.debug("[Redis] Loaded Langfuse cookies for %s", email)
            return json.loads(data)
    except Exception as e:
        logger.warning("[Redis] Failed to load cookies for %s: %s", email, e)
    return {}


def _persist_env_value(key: str, value: str) -> None:
    """Persist a key/value into local .env so values survive process restarts."""
    try:
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        lines: List[str] = []
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

        updated = False
        for index, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[index] = f"{key}={value}\n"
                updated = True
                break

        if not updated:
            if lines and not lines[-1].endswith("\n"):
                lines[-1] = lines[-1] + "\n"
            lines.append(f"{key}={value}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception as exc:
        logger.warning("[langfuse_add_org] failed to persist %s in .env: %s", key, exc)


def _pg_connect():
    """Return a psycopg2 connection using DATABASE_URL or defaults."""
    import psycopg2
    import re as _re

    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/langfuse")
    host, port, db, user, pw = "localhost", 5432, "langfuse", "postgres", "postgres"
    m = _re.match(r"postgresql://([^:]+):([^@]+)@([^:/]+):?(\d*)/(\w+)", db_url)
    if m:
        user, pw, host = m.group(1), m.group(2), m.group(3)
        port = int(m.group(4)) if m.group(4) else 5432
        db = m.group(5)
    return psycopg2.connect(
        host=host,
        port=port,
        dbname=db,
        user=user,
        password=pw,
        connect_timeout=5,
    )


async def _langfuse_admin_login(client: httpx.AsyncClient) -> bool:
    """Log the Langfuse admin into client and return whether a session was obtained."""
    admin_email = os.getenv("LANGFUSE_ADMIN_EMAIL", "")
    admin_password = os.getenv("LANGFUSE_ADMIN_PASSWORD", "")
    if not (admin_email and admin_password):
        return False
    csrf = (await client.get(f"{_LANGFUSE_ORIGIN}/api/auth/csrf")).json().get("csrfToken", "")
    await client.post(
        f"{_LANGFUSE_ORIGIN}/api/auth/callback/credentials",
        data={
            "csrfToken": csrf,
            "email": admin_email,
            "password": admin_password,
            "callbackUrl": _LANGFUSE_ORIGIN,
            "json": "true",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return any("session" in k.lower() for k in client.cookies)


async def _langfuse_admin_add_to_org(user_email: str) -> None:
    """
    Idempotently ensure user_email is in Langfuse org and project.
    Also discovers org/project IDs from DB and backfills runtime env when missing.
    """
    org_id_env = os.getenv("LANGFUSE_ORG_ID", "").strip()
    project_id_env = os.getenv("LANGFUSE_PROJECT_ID", "").strip()
    org_name = os.getenv("LANGFUSE_ORG_NAME", "MKCL").strip() or "MKCL"
    project_name = os.getenv("LANGFUSE_PROJECT_NAME", "Excel-ai-bot").strip() or "Excel-ai-bot"
    admin_email = os.getenv("LANGFUSE_ADMIN_EMAIL", "").strip().lower()

    pg = None
    cur = None
    try:
        pg = _pg_connect()
        cur = pg.cursor()

        user_id = None
        for _attempt in range(4):
            cur.execute("SELECT id FROM users WHERE LOWER(email) = LOWER(%s)", (user_email,))
            user_row = cur.fetchone()
            if user_row:
                user_id = user_row[0]
                break
            await asyncio.sleep(0.5 * (_attempt + 1))

        if not user_id:
            logger.warning("[langfuse_add_org] user_id not found for %s - skipping", user_email)
            return

        org_id = None
        if org_id_env:
            cur.execute("SELECT id FROM organizations WHERE id = %s", (org_id_env,))
            if cur.fetchone():
                org_id = org_id_env

        if not org_id:
            cur.execute(
                "SELECT id FROM organizations WHERE name = %s ORDER BY created_at ASC LIMIT 1",
                (org_name,),
            )
            row = cur.fetchone()
            if row:
                org_id = row[0]
            else:
                org_id = org_id_env or str(uuid.uuid4())
                cur.execute("INSERT INTO organizations (id, name) VALUES (%s, %s)", (org_id, org_name))

        project_id = None
        if project_id_env:
            cur.execute("SELECT id FROM projects WHERE id = %s", (project_id_env,))
            if cur.fetchone():
                project_id = project_id_env

        if not project_id:
            cur.execute(
                "SELECT id FROM projects WHERE org_id = %s AND name = %s ORDER BY created_at ASC LIMIT 1",
                (org_id, project_name),
            )
            row = cur.fetchone()
            if row:
                project_id = row[0]
            else:
                project_id = project_id_env or str(uuid.uuid4())
                cur.execute(
                    "INSERT INTO projects (id, name, org_id) VALUES (%s, %s, %s)",
                    (project_id, project_name, org_id),
                )

        if not org_id_env:
            os.environ["LANGFUSE_ORG_ID"] = org_id
            _persist_env_value("LANGFUSE_ORG_ID", org_id)
            logger.info("[langfuse_add_org] detected LANGFUSE_ORG_ID=%s", org_id)
        if not project_id_env:
            os.environ["LANGFUSE_PROJECT_ID"] = project_id
            _persist_env_value("LANGFUSE_PROJECT_ID", project_id)
            logger.info("[langfuse_add_org] detected LANGFUSE_PROJECT_ID=%s", project_id)

        is_admin_user = user_email.lower() == admin_email
        org_role = "OWNER" if is_admin_user else "MEMBER"
        project_role = "OWNER" if is_admin_user else "VIEWER"
        org_membership_id = str(uuid.uuid4())

        cur.execute(
            """
            INSERT INTO organization_memberships (id, org_id, user_id, role)
            VALUES (%s, %s, %s, %s::\"Role\")
            ON CONFLICT (org_id, user_id)
            DO UPDATE SET role = EXCLUDED.role, updated_at = CURRENT_TIMESTAMP
            RETURNING id
            """,
            (org_membership_id, org_id, user_id, org_role),
        )
        org_membership_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO project_memberships (project_id, user_id, org_membership_id, role)
            VALUES (%s, %s, %s, %s::\"Role\")
            ON CONFLICT (project_id, user_id)
            DO UPDATE SET
              org_membership_id = EXCLUDED.org_membership_id,
              role = EXCLUDED.role,
              updated_at = CURRENT_TIMESTAMP
            """,
            (project_id, user_id, org_membership_id, project_role),
        )

        pg.commit()
        logger.info("[langfuse_add_org] ensured %s in org/project (%s / %s)", user_email, org_id, project_id)
    except Exception as exc:
        if pg:
            try:
                pg.rollback()
            except Exception:
                pass
        logger.warning("[langfuse_add_org] unexpected error for %s: %s", user_email, exc)
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if pg:
            try:
                pg.close()
            except Exception:
                pass


async def ensure_langfuse_user(email: str, password: str, name: str = "") -> bool:
    """
    Ensure a Langfuse account exists for email and cache its session cookies.
    """

    async def _do_login(client: httpx.AsyncClient) -> Optional[bool]:
        try:
            csrf_resp = await client.get(f"{_LANGFUSE_ORIGIN}/api/auth/csrf")
            csrf_token = csrf_resp.json().get("csrfToken", "")
            await client.post(
                f"{_LANGFUSE_ORIGIN}/api/auth/callback/credentials",
                data={
                    "csrfToken": csrf_token,
                    "email": email,
                    "password": password,
                    "callbackUrl": _LANGFUSE_ORIGIN,
                    "json": "true",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            return any("session" in k.lower() for k in client.cookies)
        except httpx.RequestError as exc:
            logger.warning(
                "[ensure_langfuse_user] Langfuse endpoint unreachable at %s: %s",
                _LANGFUSE_ORIGIN,
                exc,
            )
            return None
        except Exception:
            return False

    try:
        # ── CHECK CACHES BEFORE HTTP LOGIN ──
        # 1. In-memory cache (fastest)
        if email in _user_langfuse_cookies:
            logger.debug("[ensure_langfuse_user] in-memory cookie hit for %s", email)
            await _langfuse_admin_add_to_org(email)
            return True

        # 2. Redis cache (survives restarts)
        redis_cookies = load_langfuse_cookies_from_redis(email)
        if redis_cookies:
            _user_langfuse_cookies[email] = redis_cookies
            logger.info("[ensure_langfuse_user] Redis cookie hit for %s — skipping HTTP login", email)
            await _langfuse_admin_add_to_org(email)
            return True

        # 3. No cache hit → full HTTP login
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as c:
            login_state = await _do_login(c)
            if login_state is True:
                cookies = dict(c.cookies)
                _user_langfuse_cookies[email] = cookies
                save_langfuse_cookies_to_redis(email, cookies)
                logger.info("[ensure_langfuse_user] existing Langfuse session ready for %s", email)
                await _langfuse_admin_add_to_org(email)
                return True
            if login_state is None:
                logger.warning(
                    "[ensure_langfuse_user] skipping signup for %s because Langfuse is unreachable",
                    email,
                )
                return False

        logger.info("[ensure_langfuse_user] registering new Langfuse account for %s", email)
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as c:
            reg = await c.post(
                f"{_LANGFUSE_ORIGIN}/api/auth/signup",
                json={
                    "email": email,
                    "password": password,
                    "name": name or email.split("@")[0],
                    "referralSource": "self-hosting",
                },
                headers={"Content-Type": "application/json"},
            )
            logger.debug("[ensure_langfuse_user] signup %s -> %s %s", email, reg.status_code, reg.text[:300])

            if reg.status_code not in (200, 201):
                logger.warning(
                    "[ensure_langfuse_user] signup failed for %s: %s %s",
                    email,
                    reg.status_code,
                    reg.text[:300],
                )
                return False

        for attempt in range(4):
            delay = 0.5 * (attempt + 1)
            await asyncio.sleep(delay)
            async with httpx.AsyncClient(follow_redirects=True, timeout=15) as c:
                login_state = await _do_login(c)
                if login_state is True:
                    cookies = dict(c.cookies)
                    _user_langfuse_cookies[email] = cookies
                    save_langfuse_cookies_to_redis(email, cookies)
                    logger.info("[ensure_langfuse_user] Langfuse session ready for %s (attempt %d)", email, attempt + 1)
                    await _langfuse_admin_add_to_org(email)
                    return True
                if login_state is None:
                    logger.warning(
                        "[ensure_langfuse_user] login retry stopped for %s because Langfuse is unreachable",
                        email,
                    )
                    return False
            logger.debug("[ensure_langfuse_user] login retry %d/4 failed for %s", attempt + 1, email)

        logger.warning(
            "[ensure_langfuse_user] could not obtain Langfuse session for %s after signup + 4 retries",
            email,
        )
        return False

    except Exception as exc:
        logger.warning("[ensure_langfuse_user] unexpected error for %s: %s", email, exc)
        return False


async def bootstrap_langfuse_admin() -> None:
    """Ensure Langfuse admin account and org/project membership exist at app startup."""
    admin_email = os.getenv("LANGFUSE_ADMIN_EMAIL", "").strip()
    admin_password = os.getenv("LANGFUSE_ADMIN_PASSWORD", "").strip()
    if not admin_email or not admin_password:
        logger.warning(
            "[langfuse_bootstrap] LANGFUSE_ADMIN_EMAIL / LANGFUSE_ADMIN_PASSWORD missing - bootstrap skipped"
        )
        return

    ok = await ensure_langfuse_user(admin_email, admin_password, "Excel AI Admin")
    if ok:
        logger.info(
            "[langfuse_bootstrap] admin bootstrap complete for %s (org=%s project=%s)",
            admin_email,
            os.getenv("LANGFUSE_ORG_ID", ""),
            os.getenv("LANGFUSE_PROJECT_ID", ""),
        )
    else:
        logger.warning("[langfuse_bootstrap] admin bootstrap incomplete for %s", admin_email)


def issue_sso_key(email: str, target_url: str, ttl_minutes: int = 5) -> str:
    key = str(uuid.uuid4())
    _sso_keys[key] = {
        "email": email,
        "target_url": target_url,
        "expires_at": (datetime.utcnow() + timedelta(minutes=ttl_minutes)).isoformat(),
    }
    return key


def consume_sso_key(key: str) -> Optional[dict]:
    data = _sso_keys.pop(key, None)
    if not data:
        return None
    expires_at = data.get("expires_at")
    if not expires_at:
        return None
    try:
        if datetime.utcnow() > datetime.fromisoformat(expires_at):
            return None
    except Exception:
        return None
    return data


__all__ = [
    "_sso_keys",
    "_user_langfuse_cookies",
    "bootstrap_langfuse_admin",
    "build_langfuse_project_url",
    "build_langfuse_session_url",
    "build_langfuse_trace_url",
    "build_langfuse_traces_url",
    "consume_sso_key",
    "ensure_langfuse_user",
    "issue_sso_key",
    "load_langfuse_cookies_from_redis",
    "save_langfuse_cookies_to_redis",
]
