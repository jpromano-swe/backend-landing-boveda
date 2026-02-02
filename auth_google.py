from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from google_auth_oauthlib.flow import Flow

from config import get_env

router = APIRouter()

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


@router.get("/auth/google/start")
def google_start():
    flow = build_flow()
    authorization_url, _state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    return RedirectResponse(authorization_url)


@router.get("/auth/google/callback")
def google_callback(request: Request):
    flow = build_flow()
    flow.fetch_token(authorization_response=str(request.url))

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
