from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import auth_google
import calendar_api
from config import get_env

app = FastAPI()

frontend_origin = get_env("FRONTEND_ORIGIN")
if frontend_origin:
    allowed_origins = [origin.strip() for origin in frontend_origin.split(",") if origin.strip()]
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

app.include_router(auth_google.router)
app.include_router(calendar_api.router)


@app.get("/health")
def health():
    return {"status": "ok"}
