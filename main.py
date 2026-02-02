from __future__ import annotations

from fastapi import FastAPI

import auth_google
import calendar_api

app = FastAPI()

app.include_router(auth_google.router)
app.include_router(calendar_api.router)


@app.get("/health")
def health():
    return {"status": "ok"}
