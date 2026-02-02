from __future__ import annotations

import base64
from datetime import datetime, timezone
from html import escape as html_escape
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, quote

import requests

from config import get_env

TEMPLATE_PATH = Path(__file__).resolve().parent / "email_template.html"


def _escape_ics(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace(";", "\\;")
        .replace("\n", "\\n")
    )


def _format_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _format_local(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def _format_date(dt: datetime) -> str:
    return dt.strftime("%d/%m/%Y")


def _format_time_range(start: datetime, end: datetime) -> str:
    return f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')}"


def _load_template() -> str | None:
    try:
        return TEMPLATE_PATH.read_text(encoding="utf-8")
    except OSError:
        return None


def _render_template(template: str, replacements: dict[str, str]) -> str:
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(key, value)
    return rendered


def _build_google_link(
    summary: str,
    start: datetime,
    end: datetime,
    details: str,
    location: str,
    tz: str,
) -> str:
    params = {
        "action": "TEMPLATE",
        "text": summary,
        "dates": f"{_format_utc(start)}/{_format_utc(end)}",
        "details": details,
        "location": location,
        "ctz": tz,
    }
    return "https://calendar.google.com/calendar/render?" + urlencode(params, quote_via=quote)


def _build_outlook_link(
    summary: str,
    start: datetime,
    end: datetime,
    details: str,
    location: str,
) -> str:
    params = {
        "subject": summary,
        "startdt": start.isoformat(),
        "enddt": end.isoformat(),
        "body": details,
        "location": location,
    }
    return "https://outlook.live.com/calendar/0/deeplink/compose?" + urlencode(params, quote_via=quote)


def build_ics(
    summary: str,
    description: str,
    location: str,
    start: datetime,
    end: datetime,
) -> str:
    uid = f"{datetime.now(timezone.utc).timestamp()}-{id(start)}"
    dtstamp = _format_utc(datetime.now(timezone.utc))

    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//DCA BTC//Booking//ES",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{dtstamp}",
            f"DTSTART:{_format_utc(start)}",
            f"DTEND:{_format_utc(end)}",
            f"SUMMARY:{_escape_ics(summary)}",
            f"DESCRIPTION:{_escape_ics(description)}",
            f"LOCATION:{_escape_ics(location)}",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )


def build_booking_email(
    *,
    name: str | None,
    summary: str,
    start: datetime,
    end: datetime,
    tz_label: str,
    meet_link: str | None,
    notes: str | None,
) -> tuple[str, str, str]:
    time_label = f"{_format_local(start)} - {_format_local(end)} ({tz_label})"
    meet_text = meet_link or "(pendiente)"
    details = f"Reunion: {summary}\nHorario: {time_label}\nMeet: {meet_text}"
    if notes:
        details += f"\nNotas: {notes}"

    google_link = _build_google_link(summary, start, end, details, meet_text, tz_label)
    outlook_link = _build_outlook_link(summary, start, end, details, meet_text)

    template = _load_template()
    if template:
        safe_name = f" {name}" if name else ""
        replacements = {
            "%%EVENT_LINK%%": google_link,
            "%%EVENT_DATE%%": html_escape(_format_date(start)),
            "%%EVENT_TIME%%": html_escape(_format_time_range(start, end)),
            "%%MEET_LINK%%": html_escape(meet_text),
            "%%MEET_LINK_URL%%": meet_text,
            "%%EVENT_TITLE%%": html_escape(summary),
            "%%NAME%%": html_escape(safe_name),
        }
        html = _render_template(template, replacements)
    else:
        greeting = f"Hola {html_escape(name)}," if name else "Hola,"
        html = f"""
        <div style="font-family:Arial,sans-serif;line-height:1.5;color:#111">
          <h2>Reserva confirmada</h2>
          <p>{greeting}</p>
          <p>Tu reunion quedo confirmada.</p>
          <p><strong>Horario:</strong> {html_escape(time_label)}</p>
          <p><strong>Meet:</strong> <a href="{html_escape(meet_text)}">{html_escape(meet_text)}</a></p>
          <p>
            <a href="{html_escape(google_link)}">Agregar a Google Calendar</a>
            &nbsp;|&nbsp;
            <a href="{html_escape(outlook_link)}">Agregar a Outlook</a>
          </p>
          <p>Si necesitas reprogramar, responde este email.</p>
        </div>
        """

    ics = build_ics(summary, details, meet_text, start, end)
    subject = f"Reserva confirmada - {summary}"
    return subject, html.strip(), ics


def send_booking_email(
    *,
    to_email: str,
    subject: str,
    html: str,
    ics: str,
) -> tuple[bool, str | None]:
    api_key = get_env("RESEND_API_KEY")
    from_email = get_env("RESEND_FROM")
    reply_to = get_env("RESEND_REPLY_TO")

    if not api_key or not from_email:
        return False, "Resend not configured"

    attachments = [
        {
            "filename": "evento.ics",
            "content": base64.b64encode(ics.encode("utf-8")).decode("ascii"),
            "content_type": "text/calendar; charset=utf-8",
        }
    ]

    payload: dict[str, Any] = {
        "from": from_email,
        "to": [to_email],
        "subject": subject,
        "html": html,
        "attachments": attachments,
    }

    if reply_to:
        payload["reply_to"] = reply_to

    response = requests.post(
        "https://api.resend.com/emails",
        json=payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )

    if response.status_code >= 400:
        return False, f"Resend error {response.status_code}: {response.text}"

    return True, None
