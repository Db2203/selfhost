"""Admin commands, run inside the api container:

    docker compose exec api python -m app.cli create-user <username>

There is intentionally no public signup endpoint — accounts on a personal
photo server are created by whoever operates the server.
"""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from app.db import SessionFactory, engine
from app.models import User
from app.security import hash_password


async def _create_user(username: str, password: str) -> str:
    async with SessionFactory() as session:
        existing = await session.execute(select(User).where(User.username == username))
        if existing.scalar_one_or_none() is not None:
            return f"user {username!r} already exists"
        session.add(User(username=username, password_hash=hash_password(password)))
        await session.commit()
        return f"created user {username!r}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-user", help="create a user account")
    create.add_argument("username")

    args = parser.parse_args(argv)

    if args.command == "create-user":
        password = getpass.getpass("Password: ")
        if len(password) < 8:
            print("password must be at least 8 characters", file=sys.stderr)
            return 1
        if password != getpass.getpass("Repeat password: "):
            print("passwords do not match", file=sys.stderr)
            return 1

        async def go() -> str:
            try:
                return await _create_user(args.username, password)
            finally:
                await engine.dispose()

        print(asyncio.run(go()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
