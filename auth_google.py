from __future__ import annotations

import logging
import os
from html import escape as html_escape
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from google_auth_oauthlib.flow import Flow

from config import get_env

router = APIRouter()
logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]


def build_flow() -> Flow:
    client_config = {
        "web": {
            "client_id": get_env("GOOGLE_CLIENT_ID", required=True),
            "client_secret": get_env("GOOGLE_CLIENT_SECRET", required=True),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    redirect_uri = get_env("GOOGLE_REDIRECT_URI", required=True)
    return Flow.from_client_config(
        client_config=client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )


def _render_error(title: str, detail: str, status_code: int = 500) -> HTMLResponse:
    safe_title = html_escape(title)
    safe_detail = html_escape(detail)
    html = f"""
    <h2>{safe_title}</h2>
    <p>{safe_detail}</p>
    """
    return HTMLResponse(html, status_code=status_code)


@router.get("/auth/google/debug")
def google_debug():
    raw_redirect = os.getenv("GOOGLE_REDIRECT_URI")
    normalized_redirect = get_env("GOOGLE_REDIRECT_URI")
    normalized_client_id = get_env("GOOGLE_CLIENT_ID")

    try:
        flow = build_flow()
        authorization_url, _state = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
        )
        parsed = urlparse(authorization_url)
        query = parse_qs(parsed.query)
        auth_redirect = query.get("redirect_uri", [None])[0]
        auth_client_id = query.get("client_id", [None])[0]
    except Exception as exc:  # pragma: no cover - runtime integration path
        logger.exception("Google OAuth debug failed")
        return {
            "ok": False,
            "error": str(exc),
            "env": {
                "redirect_uri_raw_repr": repr(raw_redirect),
                "redirect_uri_normalized": normalized_redirect,
                "client_id_tail": normalized_client_id[-12:] if normalized_client_id else None,
            },
        }

    return {
        "ok": True,
        "env": {
            "redirect_uri_raw_repr": repr(raw_redirect),
            "redirect_uri_normalized": normalized_redirect,
            "client_id_tail": normalized_client_id[-12:] if normalized_client_id else None,
        },
        "oauth_url_params": {
            "redirect_uri": auth_redirect,
            "client_id_tail": auth_client_id[-12:] if auth_client_id else None,
        },
    }


@router.get("/auth/google/start")
def google_start():
    try:
        flow = build_flow()
        authorization_url, _state = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
        )
        return RedirectResponse(authorization_url)
    except Exception as exc:  # pragma: no cover - runtime integration path
        logger.exception("Google OAuth start failed")
        return _render_error("Google OAuth start failed", str(exc), status_code=500)


@router.get("/auth/google/callback")
def google_callback(request: Request):
    try:
        flow = build_flow()
        flow.fetch_token(authorization_response=str(request.url))
    except Exception as exc:  # pragma: no cover - runtime integration path
        logger.exception("Google OAuth callback failed")
        hint = ""
        message = str(exc)
        if "invalid_grant" in message:
            hint = (
                " Invalid grant usually means code expired, token revoked, or OAuth client "
                "credentials/redirect URI do not match."
            )
        if "redirect_uri_mismatch" in message:
            hint = " Redirect URI mismatch: verify GOOGLE_REDIRECT_URI and Google OAuth settings."
        return _render_error("Google OAuth callback failed", f"{message}{hint}", status_code=500)

    creds = flow.credentials
    refresh_token = creds.refresh_token

    if not refresh_token:
        html = """
        <h2>Google Calendar connected</h2>
        <p>No refresh token returned. Make sure you used prompt=consent and access_type=offline, then try again.</p>
        """
        return HTMLResponse(html)

    html = f"""
    <h2>Google Calendar connected</h2>
    <p>Refresh token (store it in your env or DB):</p>
    <pre>{refresh_token}</pre>
    """
    return HTMLResponse(html)
