"""Management CLI for nekonoverse.

Usage:
    python -m app.cli create-admin
    python -m app.cli reset-password
    python -m app.cli create-admin --username neko --email neko@example.com --password mypassword
"""

import argparse
import asyncio
import getpass
import re
import sys

from sqlalchemy.ext.asyncio import AsyncSession

# Import all models so SQLAlchemy relationships resolve correctly
import app.models.actor  # noqa: F401
import app.models.delivery  # noqa: F401
import app.models.drive_file  # noqa: F401
import app.models.follow  # noqa: F401
import app.models.note  # noqa: F401
import app.models.oauth  # noqa: F401
import app.models.reaction  # noqa: F401
import app.models.user  # noqa: F401
from app.database import async_session, engine
from app.services.user_service import create_user, reset_password

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]+$")


def _prompt(label: str, *, default: str | None = None, required: bool = True) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if not value and default:
            return default
        if value:
            return value
        if not required:
            return ""
        print("  This field is required.")


def _prompt_password(label: str = "Password", *, confirm: bool = True, min_length: int = 8) -> str:
    while True:
        pw = getpass.getpass(f"{label}: ")
        if len(pw) < min_length:
            print(f"  Password must be at least {min_length} characters.")
            continue
        if confirm:
            pw2 = getpass.getpass(f"{label} (confirm): ")
            if pw != pw2:
                print("  Passwords do not match. Try again.")
                continue
        return pw


def _prompt_username() -> str:
    while True:
        username = _prompt("Username")
        if not _USERNAME_RE.match(username):
            print("  Username must be alphanumeric (a-z, 0-9, _).")
            continue
        if len(username) > 30:
            print("  Username must be 30 characters or less.")
            continue
        return username.lower()


def _interactive_create_admin() -> argparse.Namespace:
    print("\n  Create Admin User\n")
    args = argparse.Namespace()
    args.username = _prompt_username()
    args.email = _prompt("Email")
    args.password = _prompt_password()
    args.display_name = _prompt("Display name", default=args.username, required=False) or None
    print()
    return args


def _interactive_reset_password() -> argparse.Namespace:
    print("\n  Reset Password\n")
    args = argparse.Namespace()
    args.username = _prompt("Username")
    args.password = _prompt_password(label="New password")
    print()
    return args


async def _create_admin(args: argparse.Namespace) -> None:
    async with async_session() as db:
        db: AsyncSession
        try:
            user = await create_user(
                db=db,
                username=args.username,
                email=args.email,
                password=args.password,
                display_name=args.display_name,
                role="admin",
            )
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        print(f"Admin user created: {user.actor.username} ({user.email})")
        print(f"  role: {user.role}")
        print(f"  actor_id: {user.actor_id}")

    await engine.dispose()


async def _reset_password(args: argparse.Namespace) -> None:
    async with async_session() as db:
        try:
            user = await reset_password(db, args.username, args.password)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        print(f"Password reset for: {user.actor.username} ({user.email})")

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="nekonoverse", description="nekonoverse management CLI")
    sub = parser.add_subparsers(dest="command")

    create_admin = sub.add_parser("create-admin", help="Create an admin user")
    create_admin.add_argument("--username", default=None)
    create_admin.add_argument("--email", default=None)
    create_admin.add_argument("--password", default=None)
    create_admin.add_argument("--display-name", dest="display_name", default=None)

    reset_pw = sub.add_parser("reset-password", help="Reset a user's password")
    reset_pw.add_argument("--username", default=None)
    reset_pw.add_argument("--password", default=None)

    args = parser.parse_args()

    if args.command == "create-admin":
        if not (args.username and args.email and args.password):
            args = _interactive_create_admin()
        asyncio.run(_create_admin(args))
    elif args.command == "reset-password":
        if not (args.username and args.password):
            args = _interactive_reset_password()
        asyncio.run(_reset_password(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
