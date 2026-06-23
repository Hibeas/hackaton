#!/usr/bin/env python3
"""
Demo: Baltic Hub traffic spike → slot dispatch → voice call.

Usage (from port-ai/backend):
  python scripts/demo_baltic_hub_spike.py
  python scripts/demo_baltic_hub_spike.py --dry-run
  python scripts/demo_baltic_hub_spike.py --phone +48728538889
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from dotenv import load_dotenv

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

load_dotenv(os.path.join(BACKEND_DIR, ".env"))


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Baltic Hub spike + slot dispatch demo")
    parser.add_argument("--phone", default=os.environ.get("VOICE_CALL_DEMO_TO", "+48728538889"))
    parser.add_argument("--dry-run", action="store_true", help="Plan only, no Twilio call")
    parser.add_argument("--no-force", action="store_true", help="Respect call cooldown")
    args = parser.parse_args()

    from demo_baltic_spike_service import run_baltic_hub_spike_demo
    from observation_store import ObservationStore
    from user_store import user_store

    store = ObservationStore()
    print(f"Users DB: {user_store.backend_name} | Observations DB: {store.backend_name}")

    result = await run_baltic_hub_spike_demo(
        observation_store=store,
        phone_e164=args.phone,
        dry_run=args.dry_run,
        force_call=not args.no_force,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))

    calls = result.get("dispatch", {}).get("calls") or []
    if any(item.get("status") == "called" for item in calls):
        print("\nTelefon wysłany.")
        return 0
    if args.dry_run:
        print("\nDry-run — sprawdź alerts powyżej.")
        return 0
    print("\nBrak połączenia — sprawdź alerts i konfigurację Twilio.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
