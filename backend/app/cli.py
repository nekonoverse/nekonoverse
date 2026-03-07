"""Management CLI for nekonoverse.

Usage:
    python -m app.cli create-admin --username neko --email neko@example.com --password mypassword
"""

import argparse
import asyncio
import sys

from sqlalchemy.ext.asyncio import AsyncSession

# Import all models so SQLAlchemy relationships resolve correctly
import app.models.actor  # noqa: F401
import app.models.delivery  # noqa: F401
import app.models.follow  # noqa: F401
import app.models.note  # noqa: F401
import app.models.oauth  # noqa: F401
import app.models.drive_file  # noqa: F401
import app.models.reaction  # noqa: F401
import app.models.user  # noqa: F401
from app.database import async_session, engine
from app.services.user_service import create_user, reset_password


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
    create_admin.add_argument("--username", required=True)
    create_admin.add_argument("--email", required=True)
    create_admin.add_argument("--password", required=True)
    create_admin.add_argument("--display-name", dest="display_name", default=None)

    reset_pw = sub.add_parser("reset-password", help="Reset a user's password")
    reset_pw.add_argument("--username", required=True)
    reset_pw.add_argument("--password", required=True)

    args = parser.parse_args()

    if args.command == "create-admin":
        asyncio.run(_create_admin(args))
    elif args.command == "reset-password":
        asyncio.run(_reset_password(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
