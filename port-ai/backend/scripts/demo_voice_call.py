#!/usr/bin/env python3
"""
Demo: outbound voice alert via ElevenLabs + Twilio.

Usage (from port-ai/backend):
  cp .env.example .env   # fill TWILIO_* and ELEVENLABS_*
  pip install twilio httpx
  python scripts/demo_voice_call.py --to +48123456789 --message "Alert test"

Trial Twilio accounts can only call verified numbers.
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

load_dotenv(os.path.join(BACKEND_DIR, ".env"))

from voice_call_service import is_voice_call_configured, make_automated_voice_call_sync


def main() -> int:
    parser = argparse.ArgumentParser(description="Demo ElevenLabs + Twilio voice call")
    parser.add_argument(
        "--to",
        default=os.environ.get("VOICE_CALL_DEMO_TO", ""),
        help="Destination E.164 number, e.g. +48728538889",
    )
    parser.add_argument(
        "--message",
        default=(
            "Uwaga! Jedzie dziekan. Jedzie dziekan. Jedzie dziekan. Jedzie dziekan."
        ),
        help="Phrase the agent should speak",
    )
    args = parser.parse_args()

    if not args.to:
        print("Error: pass --to or set VOICE_CALL_DEMO_TO in .env", file=sys.stderr)
        return 1

    if not is_voice_call_configured():
        print(
            "Error: set TWILIO_* and ELEVENLABS_* in backend/.env (see .env.example)",
            file=sys.stderr,
        )
        return 1

    try:
        result = make_automated_voice_call_sync(args.to, args.message)
    except Exception as exc:
        print(f"Call failed: {exc}", file=sys.stderr)
        return 1

    print("Call initiated successfully.")
    print(f"  Twilio SID: {result['call_sid']}")
    print(f"  To:         {result['to_number']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
