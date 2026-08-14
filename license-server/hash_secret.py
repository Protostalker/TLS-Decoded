#!/usr/bin/env python3
"""
Turn a secret you choose into the hash that goes in your .env file — run
this once per secret, paste the printed line into .env/.env.cloud, and
never store the raw secret there. See auth.py's module docstring for why
LICENSE_SERVER_ADMIN_TOKEN and UNLIMITED_LICENSE_PASSPHRASE use different
hash algorithms (SHA-256 for the random token, bcrypt for the human-chosen
passphrase).

Usage:
  python3 hash_secret.py --type admin-token
  python3 hash_secret.py --type passphrase

Input is hidden (getpass) and asked twice to catch typos. Nothing is
written to disk or sent anywhere — this only prints to stdout.
"""
import argparse
import getpass
import hashlib
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--type", choices=["admin-token", "passphrase"], required=True,
                         help="admin-token: LICENSE_SERVER_ADMIN_TOKEN_HASH (SHA-256). "
                              "passphrase: UNLIMITED_LICENSE_PASSPHRASE_HASH (bcrypt).")
    args = parser.parse_args()

    secret = getpass.getpass("Secret to hash (input hidden): ")
    if not secret:
        print("Empty secret — aborting.", file=sys.stderr)
        return 1
    confirm = getpass.getpass("Confirm: ")
    if secret != confirm:
        print("Did not match — try again.", file=sys.stderr)
        return 1

    if args.type == "admin-token":
        digest = hashlib.sha256(secret.encode()).hexdigest()
        print(f"\nLICENSE_SERVER_ADMIN_TOKEN_HASH={digest}")
    else:
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        print(f"\nUNLIMITED_LICENSE_PASSPHRASE_HASH={pwd_context.hash(secret)}")

    print("\nPaste that line into .env / .env.cloud, then restart license-server. "
          "The plaintext secret above is never stored anywhere — keep it somewhere "
          "safe yourself (password manager) since it can't be recovered from the hash.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
