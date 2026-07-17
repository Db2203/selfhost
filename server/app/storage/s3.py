from collections.abc import AsyncIterator

from aiobotocore.session import get_session

from app.storage.base import Storage, StoragePathError


class S3Storage(Storage):
    """S3-compatible backend (AWS S3, MinIO, most NAS object stores)."""

    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
    ):
        self.bucket = bucket
        self._session = get_session()
        self._client_kwargs = {
            "endpoint_url": endpoint_url or None,
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "region_name": region,
        }

    def _client(self):
        return self._session.create_client("s3", **self._client_kwargs)

    @staticmethod
    def _key(path: str) -> str:
        key = path.lstrip("/")
        if not key or ".." in key.split("/"):
            raise StoragePathError(f"invalid object key: {path!r}")
        return key

    async def read(self, path: str) -> bytes:
        async with self._client() as client:
            response = await client.get_object(Bucket=self.bucket, Key=self._key(path))
            async with response["Body"] as body:
                return await body.read()

    async def write(self, path: str, data: bytes) -> None:
        async with self._client() as client:
            await client.put_object(Bucket=self.bucket, Key=self._key(path), Body=data)

    async def exists(self, path: str) -> bool:
        async with self._client() as client:
            try:
                await client.head_object(Bucket=self.bucket, Key=self._key(path))
                return True
            except client.exceptions.ClientError as exc:
                if exc.response["ResponseMetadata"]["HTTPStatusCode"] == 404:
                    return False
                raise

    async def delete(self, path: str) -> None:
        async with self._client() as client:
            await client.delete_object(Bucket=self.bucket, Key=self._key(path))

    async def size(self, path: str) -> int:
        async with self._client() as client:
            response = await client.head_object(Bucket=self.bucket, Key=self._key(path))
            return response["ContentLength"]

    async def stream(
        self,
        path: str,
        chunk_size: int = 1024 * 1024,
        offset: int = 0,
        length: int | None = None,
    ) -> AsyncIterator[bytes]:
        kwargs = {}
        if offset or length is not None:
            # S3 does the slicing server-side.
            end = "" if length is None else str(offset + length - 1)
            kwargs["Range"] = f"bytes={offset}-{end}"
        async with self._client() as client:
            response = await client.get_object(Bucket=self.bucket, Key=self._key(path), **kwargs)
            # The body is an aiohttp response; size-bounded reads go through
            # its content StreamReader (plain .read() takes no size here).
            async with response["Body"] as body:
                async for chunk in body.content.iter_chunked(chunk_size):
                    yield chunk

    async def list_files(self, prefix: str = "") -> AsyncIterator[str]:
        async with self._client() as client:
            paginator = client.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    yield obj["Key"]
