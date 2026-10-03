"""Manage console users from the command line (docs/08 §9).

  python -m nafa_console.users add owner --role owner     # prompts for a password, prints the TOTP setup
  python -m nafa_console.users add reviewer --role viewer
  python -m nafa_console.users password owner
  python -m nafa_console.users totp owner                 # new authenticator secret
  python -m nafa_console.users list
  python -m nafa_console.users remove reviewer

In the container: docker exec -it nafa-console python -m nafa_console.users add owner
"""

from __future__ import annotations

import argparse
import getpass
import sys

from .settings import Settings
from .store import Store


def _password() -> str:
    a = getpass.getpass("Password (12+ characters): ")
    b = getpass.getpass("Again: ")
    if a != b:
        sys.exit("Passwords differ.")
    return a


def _show_totp(auth, user: str, secret: str) -> None:
    print("\nAdd this account to your authenticator app (Google Authenticator, 1Password, …):")
    print(f"  secret : {secret}")
    print(f"  link   : {auth.otpauth_uri(user, secret)}")
    print("Keep the secret private. Codes are 6 digits and change every 30 seconds.\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="nafa_console.users")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("username")
    a.add_argument("--role", choices=("owner", "viewer"), default="viewer")
    for name in ("password", "totp", "remove"):
        sub.add_parser(name).add_argument("username")
    sub.add_parser("list")
    args = ap.parse_args(argv)
    auth = Store(Settings().db_path).auth
    if args.cmd == "add":
        secret = auth.add_user(args.username, _password(), args.role)
        print(f"Added {args.username} ({args.role}).")
        _show_totp(auth, args.username, secret)
    elif args.cmd == "password":
        auth.set_password(args.username, _password())
        print("Password changed; existing sessions were signed out.")
    elif args.cmd == "totp":
        _show_totp(auth, args.username, auth.reset_totp(args.username))
    elif args.cmd == "remove":
        auth.remove_user(args.username)
        print(f"Removed {args.username}.")
    else:
        for u in auth.users():
            print(f"{u['username']:20} {u['role']:7} created {u['created']}" + (f"  locked until {u['locked_until']}" if u["locked_until"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
