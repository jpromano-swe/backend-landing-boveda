from __future__ import annotations

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import get_env

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]


def get_calendar_service():
    refresh_token = get_env("GOOGLE_REFRESH_TOKEN", required=True)
    client_id = get_env("GOOGLE_CLIENT_ID", required=True)
    client_secret = get_env("GOOGLE_CLIENT_SECRET", required=True)

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)
