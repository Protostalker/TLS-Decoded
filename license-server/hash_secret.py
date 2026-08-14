#!/usr/bin/env python3
"""
Turn your chosen admin token into the hash that goes in your .env file as
LICENSE_SERVER_ADMIN_TOKEN_HASH — run this once, paste the printed line
into .env/.env.cloud, and never store the raw token there.

Usage:
  python3 hash_secret.py

Input is hidden (getpass) and asked twice to catch typos. Nothing is
written to disk or sent anywhere — this only prints to stdout.
"""
import getpass
import hashlib
import sys


def main() -> int:
    secret = getpass.getpass("Admin token to hash (input hidden): ")
    if not secret:
        print("Empty secret — aborting.", file=sys.stderr)
        return 1
    confirm = getpass.getpass("Confirm: ")
    if secret != confirm:
        print("Did not match — try again.", file=sys.stderr)
        return 1

    digest = hashlib.sha256(secret.encode()).hexdigest()
    print(f"\nLICENSE_SERVER_ADMIN_TOKEN_HASH={digest}")
    print("\nPaste that line into .env / .env.cloud, then restart license-server. "
          "The plaintext token above is never stored anywhere — keep it somewhere "
          "safe yourself (password manager) since it can't be recovered from the hash.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
