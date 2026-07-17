import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_session
from app.deps import AuthContext, get_auth
from app.models import Album, AlbumAsset, Asset, Thumbnail
from app.routers.assets import asset_to_out
from app.schemas import AlbumAssetIds, AlbumName, AlbumOut, AssetOut
from app.signing import sign_asset_url

router = APIRouter(prefix="/albums", tags=["albums"])


async def _get_owned_album(
    session: AsyncSession, owner_id: uuid.UUID, album_id: uuid.UUID
) -> Album:
    album = (
        await session.execute(
            select(Album).where(Album.id == album_id, Album.owner_id == owner_id)
        )
    ).scalar_one_or_none()
    if album is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown album")
    return album


async def _to_out(session: AsyncSession, album: Album) -> AlbumOut:
    asset_count = (
        await session.scalar(
            select(func.count(AlbumAsset.id)).where(AlbumAsset.album_id == album.id)
        )
    ) or 0
    # Cover: grid thumbnail of the most recently added member.
    cover_asset_id = (
        await session.execute(
            select(Thumbnail.asset_id)
            .join(AlbumAsset, AlbumAsset.asset_id == Thumbnail.asset_id)
            .where(AlbumAsset.album_id == album.id, Thumbnail.kind == "grid")
            .order_by(AlbumAsset.added_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return AlbumOut(
        id=album.id,
        name=album.name,
        created_at=album.created_at,
        asset_count=asset_count,
        cover=sign_asset_url(cover_asset_id, "grid") if cover_asset_id else None,
    )


@router.get("", response_model=list[AlbumOut])
async def list_albums(
    auth: Annotated[AuthContext, Depends(get_auth)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AlbumOut]:
    albums = (
        (
            await session.execute(
                select(Album)
                .where(Album.owner_id == auth.user.id)
                .order_by(Album.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [await _to_out(session, album) for album in albums]


@router.post("", response_model=AlbumOut, status_code=status.HTTP_201_CREATED)
async def create_album(
    body: AlbumName,
    auth: Annotated[AuthContext, Depends(get_auth)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AlbumOut:
    album = Album(owner_id=auth.user.id, name=body.name)
    session.add(album)
    await session.commit()
    return await _to_out(session, album)


@router.patch("/{album_id}", response_model=AlbumOut)
async def rename_album(
    album_id: uuid.UUID,
    body: AlbumName,
    auth: Annotated[AuthContext, Depends(get_auth)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AlbumOut:
    album = await _get_owned_album(session, auth.user.id, album_id)
    album.name = body.name
    await session.commit()
    return await _to_out(session, album)


@router.delete("/{album_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_album(
    album_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(get_auth)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Delete the album itself; its assets stay in the library."""
    album = await _get_owned_album(session, auth.user.id, album_id)
    await session.execute(delete(AlbumAsset).where(AlbumAsset.album_id == album.id))
    await session.execute(delete(Album).where(Album.id == album.id))
    await session.commit()


@router.post("/{album_id}/assets", status_code=status.HTTP_204_NO_CONTENT)
async def add_assets(
    album_id: uuid.UUID,
    body: AlbumAssetIds,
    auth: Annotated[AuthContext, Depends(get_auth)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Add assets to the album. Only the caller's own assets count; ids
    already present are skipped, so the call is idempotent."""
    album = await _get_owned_album(session, auth.user.id, album_id)

    owned = set(
        (
            await session.execute(
                select(Asset.id).where(
                    Asset.owner_id == auth.user.id, Asset.id.in_(body.asset_ids)
                )
            )
        ).scalars()
    )
    if not owned:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such assets")

    present = set(
        (
            await session.execute(
                select(AlbumAsset.asset_id).where(
                    AlbumAsset.album_id == album.id, AlbumAsset.asset_id.in_(owned)
                )
            )
        ).scalars()
    )
    for asset_id in owned - present:
        session.add(AlbumAsset(album_id=album.id, asset_id=asset_id))
    await session.commit()


@router.delete("/{album_id}/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_asset(
    album_id: uuid.UUID,
    asset_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(get_auth)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    album = await _get_owned_album(session, auth.user.id, album_id)
    await session.execute(
        delete(AlbumAsset).where(
            AlbumAsset.album_id == album.id, AlbumAsset.asset_id == asset_id
        )
    )
    await session.commit()


@router.get("/{album_id}/assets", response_model=list[AssetOut])
async def album_assets(
    album_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(get_auth)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AssetOut]:
    album = await _get_owned_album(session, auth.user.id, album_id)
    result = await session.execute(
        select(Asset)
        .join(AlbumAsset, AlbumAsset.asset_id == Asset.id)
        .where(AlbumAsset.album_id == album.id)
        .options(selectinload(Asset.thumbnails))
        .order_by(Asset.taken_at.desc().nulls_last(), Asset.created_at.desc())
    )
    return [asset_to_out(a) for a in result.scalars()]
