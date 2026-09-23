#!/usr/bin/env python3
"""Submit a proofs JSONL to the Lean Refactor Arena Space, and check on it.

  pip install gradio_client
  python3 competition/submit_space.py --user Bob --file submissions/terra-1.jsonl
  python3 competition/submit_space.py --user Bob --status

Usernames are claimed on first submission. The Space then returns a
one-time submission key, required for every later submission or status
check under that name. It is saved to .secrets/space_<user>.key (gitignored,
mode 600) and never printed: losing it means losing the name.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

SPACE = "delta-lab-ai/lean-refactor-arena"
SECRETS = Path(__file__).resolve().parent.parent / ".secrets"
TRACKS = {"closed": "Closed-source LLM", "open": "Open-source LLM"}
KEY_RE = re.compile(r"submission key: `([^`]+)`")


def key_path(user: str) -> Path:
    return SECRETS / f"space_{re.sub(r'[^A-Za-z0-9_.-]', '_', user)}.key"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user", required=True)
    ap.add_argument("--file", type=Path)
    ap.add_argument("--track", choices=sorted(TRACKS), default="closed")
    ap.add_argument("--status", action="store_true", help="show this user's submissions instead")
    args = ap.parse_args()

    from gradio_client import Client, handle_file

    kp = key_path(args.user)
    key = kp.read_text().strip() if kp.exists() else ""
    client = Client(SPACE, verbose=False)

    if args.status:
        if not key:
            sys.exit(f"no saved key for {args.user!r} at {kp}")
        print(client.predict(args.user, key, api_name="/view_submissions"))
        return

    if not args.file or not args.file.is_file():
        sys.exit("--file must be an existing JSONL")
    _, message = client.predict(args.user, key, TRACKS[args.track], handle_file(str(args.file)),
                                api_name="/verify_and_submit")
    minted = KEY_RE.search(message or "")
    if minted:
        SECRETS.mkdir(mode=0o700, exist_ok=True)
        kp.write_text(minted.group(1) + "\n")
        os.chmod(kp, 0o600)
        message = KEY_RE.sub(f"submission key: `<saved to {kp}>`", message)
    print(message)


if __name__ == "__main__":
    main()
