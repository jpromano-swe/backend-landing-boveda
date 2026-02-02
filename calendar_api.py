from __future__ import annotations

from datetime import datetime, time, timedelta
from uuid import uuid4
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from googleapiclient.errors import HttpError
from google.auth.exceptions import RefreshError

from config import get_env
from google_calendar_client import get_calendar_service
from email_resend import build_booking_email, send_booking_email

router = APIRouter()

SLOT_HOURS = [(18, 19), (19, 20), (20, 21)]
WEEKDAYS = {0, 1, 2, 3, 4}
DEFAULT_DAYS = 10


def parse_rfc3339(value: str) -> datetime:
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    return datetime.fromisoformat(value)


def get_timezone() -> ZoneInfo:
    tz_name = get_env("GOOGLE_TZ") or "UTC"
    return ZoneInfo(tz_name)


def get_calendar_id() -> str:
    return get_env("GOOGLE_CALENDAR_ID") or "primary"


def week_bounds(now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    local_now = now.astimezone(tz)
    week_start_date = local_now.date() - timedelta(days=local_now.weekday())
    week_start = datetime.combine(week_start_date, time.min, tz)
    week_end = week_start + timedelta(days=7)
    return week_start, week_end


def ensure_tz(dt: datetime, tz: ZoneInfo) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def overlaps(start: datetime, end: datetime, busy: list[tuple[datetime, datetime]]) -> bool:
    for busy_start, busy_end in busy:
        if start < busy_end and end > busy_start:
            return True
    return False


def fetch_busy(time_min: datetime, time_max: datetime) -> list[tuple[datetime, datetime]]:
    service = get_calendar_service()
    calendar_id = get_calendar_id()

    body = {
        "timeMin": time_min.isoformat(),
        "timeMax": time_max.isoformat(),
        "items": [{"id": calendar_id}],
    }

    response = service.freebusy().query(body=body).execute()
    busy_raw = response.get("calendars", {}).get(calendar_id, {}).get("busy", [])
    busy: list[tuple[datetime, datetime]] = []
    for item in busy_raw:
        busy.append((parse_rfc3339(item["start"]), parse_rfc3339(item["end"])) )
    return busy


def build_event_body(start: datetime, end: datetime, req: "BookingRequest", tz: ZoneInfo) -> dict[str, Any]:
    summary = req.summary or "Reserva"
    description_parts = []
    if req.name:
        description_parts.append(f"Name: {req.name}")
    if req.email:
        description_parts.append(f"Email: {req.email}")
    if req.notes:
        description_parts.append(f"Notes: {req.notes}")

    event: dict[str, Any] = {
        "summary": summary,
        "start": {"dateTime": start.isoformat(), "timeZone": tz.key},
        "end": {"dateTime": end.isoformat(), "timeZone": tz.key},
        "conferenceData": {
            "createRequest": {
                "requestId": uuid4().hex,
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }
    if description_parts:
        event["description"] = "\n".join(description_parts)
    if req.email:
        event["attendees"] = [{"email": req.email}]
    return event


class BookingRequest(BaseModel):
    start: datetime
    end: datetime
    name: str | None = None
    email: str | None = None
    notes: str | None = None
    summary: str | None = None


@router.get("/calendar/availability")
def calendar_availability(days: int = Query(DEFAULT_DAYS, ge=1, le=31)):
    tz = get_timezone()
    now = datetime.now(tz)
    week_start, week_end = week_bounds(now, tz)

    range_end = now + timedelta(days=days)
    if range_end > week_end:
        range_end = week_end

    if range_end <= now:
        return {"tz": tz.key, "range": {"start": now.isoformat(), "end": range_end.isoformat()}, "slots": []}

    try:
        busy = fetch_busy(now, range_end)
    except (RuntimeError, RefreshError) as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except HttpError as exc:
        raise HTTPException(status_code=502, detail=f"Google API error: {exc}")

    slots: list[dict[str, str]] = []
    cursor = now.date()
    end_date = range_end.date()

    while cursor <= end_date:
        if cursor.weekday() in WEEKDAYS:
            for start_hour, end_hour in SLOT_HOURS:
                start_dt = datetime.combine(cursor, time(start_hour, 0), tz)
                end_dt = datetime.combine(cursor, time(end_hour, 0), tz)
                if start_dt < now:
                    continue
                if start_dt < week_start or start_dt >= week_end:
                    continue
                if overlaps(start_dt, end_dt, busy):
                    continue
                slots.append(
                    {
                        "start": start_dt.isoformat(),
                        "end": end_dt.isoformat(),
                        "label": f"{start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}",
                    }
                )
        cursor += timedelta(days=1)

    return {
        "tz": tz.key,
        "range": {"start": now.isoformat(), "end": range_end.isoformat()},
        "week": {"start": week_start.isoformat(), "end": week_end.isoformat()},
        "slots": slots,
    }


@router.post("/calendar/book")
def calendar_book(req: BookingRequest):
    tz = get_timezone()
    now = datetime.now(tz)
    week_start, week_end = week_bounds(now, tz)

    start = ensure_tz(req.start, tz)
    end = ensure_tz(req.end, tz)

    if end <= start:
        raise HTTPException(status_code=400, detail="end must be after start")
    if end - start != timedelta(hours=1):
        raise HTTPException(status_code=400, detail="slot must be 60 minutes")
    if start.weekday() not in WEEKDAYS:
        raise HTTPException(status_code=400, detail="slot must be Monday-Friday")
    if start.hour not in {18, 19, 20} or start.minute != 0:
        raise HTTPException(status_code=400, detail="slot must start at 18:00, 19:00, or 20:00")
    if start < now:
        raise HTTPException(status_code=400, detail="slot must be in the future")
    if start < week_start or start >= week_end:
        raise HTTPException(status_code=400, detail="slot must be within the current week")

    try:
        busy = fetch_busy(start, end)
    except (RuntimeError, RefreshError) as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except HttpError as exc:
        raise HTTPException(status_code=502, detail=f"Google API error: {exc}")

    if overlaps(start, end, busy):
        raise HTTPException(status_code=409, detail="slot_taken")

    calendar_id = get_calendar_id()
    event_body = build_event_body(start, end, req, tz)

    try:
        service = get_calendar_service()
        created = (
            service.events()
            .insert(calendarId=calendar_id, body=event_body, conferenceDataVersion=1)
            .execute()
        )
    except (RuntimeError, RefreshError) as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except HttpError as exc:
        raise HTTPException(status_code=502, detail=f"Google API error: {exc}")

    meet_link = created.get("hangoutLink")
    if not meet_link:
        entry_points = created.get("conferenceData", {}).get("entryPoints", [])
        for entry in entry_points:
            if entry.get("entryPointType") == "video":
                meet_link = entry.get("uri")
                break

    email_status = None
    email_error = None
    if req.email:
        subject, html, ics = build_booking_email(
            name=req.name,
            summary=req.summary or "Reserva",
            start=start,
            end=end,
            tz_label=tz.key,
            meet_link=meet_link,
            notes=req.notes,
        )
        ok, err = send_booking_email(to_email=req.email, subject=subject, html=html, ics=ics)
        email_status = "sent" if ok else "failed"
        email_error = err

    response = {"status": "booked", "eventId": created.get("id"), "meetLink": meet_link}
    if email_status:
        response["emailStatus"] = email_status
    if email_error:
        response["emailError"] = email_error

    return response
