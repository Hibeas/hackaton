"""
Outbound voice alerts via ElevenLabs Conversational AI + Twilio.

Credentials from environment (see backend/.env.example). Do not hardcode secrets.

VOICE_CALL_MODE:
  agent  — ElevenLabs convai agent (register-call + Twilio Stream)
  say    — Twilio <Say> polski (pewny tekst słowo w słowo, bez agenta)
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any
from xml.sax.saxutils import escape

import httpx

logger = logging.getLogger(__name__)

ELEVENLABS_REGISTER_CALL_URL = "https://api.elevenlabs.io/v1/convai/twilio/register-call"
PHONE_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def voice_call_mode() -> str:
    return (_env("VOICE_CALL_MODE") or "agent").lower()


def twilio_account_sid() -> str:
    return _env("TWILIO_ACCOUNT_SID")


def twilio_auth_token() -> str:
    return _env("TWILIO_AUTH_TOKEN")


def twilio_from_number() -> str:
    return normalize_phone_number(_env("TWILIO_NUMBER"))


def elevenlabs_api_key() -> str:
    return _env("ELEVENLABS_API_KEY")


def elevenlabs_agent_id() -> str:
    return _env("ELEVENLABS_AGENT_ID")


def is_voice_call_configured() -> bool:
    mode = voice_call_mode()
    if mode == "say":
        return all((twilio_account_sid(), twilio_auth_token(), twilio_from_number()))
    return all(
        (
            twilio_account_sid(),
            twilio_auth_token(),
            twilio_from_number(),
            elevenlabs_api_key(),
            elevenlabs_agent_id(),
        )
    )


def normalize_phone_number(raw: str) -> str:
    compact = re.sub(r"[\s\-()]", "", raw.strip())
    return compact


def validate_phone_number(number: str) -> str:
    normalized = normalize_phone_number(number)
    if not PHONE_E164_RE.match(normalized):
        raise ValueError(f"Invalid E.164 phone number: {number!r}")
    return normalized


def _build_conversation_initiation_data(message: str) -> dict[str, Any]:
    """
    Override ONLY first_message — do not replace agent prompt/TTS config (causes silence).
    """
    text = message.strip()
    return {
        "conversation_config_override": {
            "agent": {
                "first_message": text,
            },
        },
    }


def _build_twilio_say_twiml(message: str) -> str:
    """Reliable one-shot Polish TTS via Twilio (hackathon / demo fallback)."""
    safe = escape(message.strip())
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Say language="pl-PL" voice="Polly.Ola-Neural">{safe}</Say>'
        '<Pause length="1"/>'
        f'<Say language="pl-PL" voice="Polly.Ola-Neural">Do widzenia.</Say>'
        "</Response>"
    )


def _parse_elevenlabs_twiml(response_text: str) -> str:
    twiml = response_text.strip()
    if twiml.startswith('"') and twiml.endswith('"'):
        twiml = twiml[1:-1].replace('\\"', '"').replace("\\n", "\n")
    if not twiml or "<Response>" not in twiml:
        raise RuntimeError(f"ElevenLabs did not return valid TwiML: {twiml[:200]!r}")
    return twiml


async def register_elevenlabs_twiml(
    *,
    to_number: str,
    message: str,
    from_number: str | None = None,
    agent_id: str | None = None,
    api_key: str | None = None,
) -> str:
    payload = {
        "agent_id": agent_id or elevenlabs_agent_id(),
        "from_number": from_number or twilio_from_number(),
        "to_number": to_number,
        "direction": "outbound",
        "conversation_initiation_client_data": _build_conversation_initiation_data(message),
    }
    headers = {
        "xi-api-key": api_key or elevenlabs_api_key(),
        "Content-Type": "application/json",
    }

    logger.info("ElevenLabs register-call first_message=%r", message.strip()[:120])

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            ELEVENLABS_REGISTER_CALL_URL,
            json=payload,
            headers=headers,
        )

    if response.status_code != 200:
        raise RuntimeError(
            f"ElevenLabs API error ({response.status_code}): {response.text}"
        )

    return _parse_elevenlabs_twiml(response.text)


def place_twilio_call(*, to_number: str, twiml: str, from_number: str | None = None) -> str:
    try:
        from twilio.rest import Client
    except ImportError as exc:
        raise RuntimeError("twilio package not installed (pip install twilio)") from exc

    client = Client(twilio_account_sid(), twilio_auth_token())
    call = client.calls.create(
        to=to_number,
        from_=from_number or twilio_from_number(),
        twiml=twiml,
    )
    return str(call.sid)


async def resolve_call_twiml(to_number: str, message: str) -> tuple[str, str]:
    mode = voice_call_mode()
    if mode == "say":
        return _build_twilio_say_twiml(message), "twilio_say"
    twiml = await register_elevenlabs_twiml(to_number=to_number, message=message)
    return twiml, "elevenlabs_agent"


async def make_automated_voice_call(to_number: str, message: str) -> dict[str, Any]:
    if not is_voice_call_configured():
        raise RuntimeError("Voice call credentials are not configured (see .env.example)")

    if not message.strip():
        raise ValueError("message must not be empty")

    normalized_to = validate_phone_number(to_number)
    twiml, strategy = await resolve_call_twiml(normalized_to, message)
    call_sid = place_twilio_call(to_number=normalized_to, twiml=twiml)

    logger.info("Twilio call started: sid=%s to=%s strategy=%s", call_sid, normalized_to, strategy)
    return {
        "ok": True,
        "call_sid": call_sid,
        "to_number": normalized_to,
        "from_number": twilio_from_number(),
        "strategy": strategy,
    }


def make_automated_voice_call_sync(to_number: str, message: str) -> dict[str, Any]:
    import asyncio

    return asyncio.run(make_automated_voice_call(to_number, message))
