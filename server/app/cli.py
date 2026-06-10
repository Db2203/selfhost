"""Admin commands, run inside the api container:

    docker compose exec api python -m app.cli create-user <username>
    docker compose exec api python -m app.cli index <username>

There is intentionally no public signup endpoint — accounts on a personal
photo server are created by whoever operates the server.
"""

import argparse
import asyncio
import getpass
import sys

from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionFactory, engine
from app.models import User
from app.security import hash_password


async def _get_user_id(username: str) -> str | None:
    async with SessionFactory() as session:
        result = await session.execute(select(User.id).where(User.username == username))
        user_id = result.scalar_one_or_none()
        return str(user_id) if user_id else None


async def _enqueue_index(username: str) -> str:
    user_id = await _get_user_id(username)
    if user_id is None:
        return f"no such user: {username!r}"

    pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        job = await pool.enqueue_job("index_library_job", user_id)
        report = await job.result(timeout=3600)
        thumbs_job = await pool.enqueue_job("thumbnail_backlog_job")
        thumbs = await thumbs_job.result(timeout=3600)
        embed_job = await pool.enqueue_job("embed_backlog_job")
        embeds = await embed_job.result(timeout=7200)  # first run downloads CLIP
        faces_job = await pool.enqueue_job("detect_faces_job")
        faces = await faces_job.result(timeout=7200)
        cluster_job = await pool.enqueue_job("cluster_faces_job", user_id)
        clusters = await cluster_job.result(timeout=3600)
    finally:
        await pool.close()
    errors = report["errors"] + thumbs["errors"] + embeds["errors"] + faces["errors"]
    return (
        f"scanned={report['scanned']} added={report['added']}"
        f" duplicates={report['skipped_duplicates']}"
        f" thumbnails={thumbs['generated']} embedded={embeds['embedded']}"
        f" faces={faces['faces_found']} people+={clusters['new_people']}"
        f" errors={len(errors)}" + ("".join(f"\n  ! {e}" for e in errors))
    )


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

    index = sub.add_parser("index", help="scan the photo library for a user")
    index.add_argument("username")

    sub.add_parser(
        "copy-storage",
        help="copy every object from local media storage to the configured S3 bucket",
    )

    args = parser.parse_args(argv)

    if args.command == "copy-storage":

        async def go_copy() -> str:
            from app.config import get_settings
            from app.storage import LocalFilesystemStorage
            from app.storage.s3 import S3Storage

            settings = get_settings()
            source = LocalFilesystemStorage(settings.storage_root)
            dest = S3Storage(
                bucket=settings.s3_bucket,
                endpoint_url=settings.s3_endpoint,
                access_key=settings.s3_access_key,
                secret_key=settings.s3_secret_key,
                region=settings.s3_region,
            )
            copied = skipped = 0
            async for path in source.list_files():
                if await dest.exists(path):
                    skipped += 1
                    continue
                await dest.write(path, await source.read(path))
                copied += 1
            return f"copied={copied} skipped={skipped} (set STORAGE_BACKEND=s3 to switch over)"

        print(asyncio.run(go_copy()))
        return 0

    if args.command == "index":

        async def go_index() -> str:
            try:
                return await _enqueue_index(args.username)
            finally:
                await engine.dispose()

        result = asyncio.run(go_index())
        print(result)
        return 1 if result.startswith("no such user") else 0

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
