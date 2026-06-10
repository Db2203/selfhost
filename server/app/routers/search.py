from collections.abc import Awaitable, Callable
from typing import Annotated

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.deps import AuthContext, get_auth
from app.routers.assets import asset_to_out
from app.schemas import AssetOut, SearchResults
from app.search import search_assets

router = APIRouter(prefix="/search", tags=["search"])

QueryEmbedder = Callable[[str], Awaitable[list[float]]]

_pool = None


async def get_query_embedder() -> QueryEmbedder:
    """Embed query text by delegating to the worker (which holds the model)."""

    async def embed(query: str) -> list[float]:
        global _pool
        if _pool is None:
            _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
        job = await _pool.enqueue_job("embed_text_job", query)
        result = await job.result(timeout=30)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Search backend unavailable",
            )
        return result

    return embed


@router.get("", response_model=SearchResults)
async def search(
    q: Annotated[str, Query(min_length=1, max_length=500)],
    auth: Annotated[AuthContext, Depends(get_auth)],
    session: Annotated[AsyncSession, Depends(get_session)],
    embed: Annotated[QueryEmbedder, Depends(get_query_embedder)],
    limit: Annotated[int, Query(ge=1, le=100)] = 60,
) -> SearchResults:
    query_vector = await embed(q)
    assets = await search_assets(session, auth.user.id, query_vector, limit)
    return SearchResults(query=q, items=[asset_to_out(a) for a in assets])


__all__ = ["router", "get_query_embedder", "AssetOut"]
