import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_auth
from app.models import Asset, Face, Person, Thumbnail
from app.schemas import PersonMerge, PersonOut, PersonRename
from app.signing import sign_asset_url

router = APIRouter(prefix="/people", tags=["people"])


async def _get_owned_person(
    session: AsyncSession, owner_id: uuid.UUID, person_id: uuid.UUID
) -> Person:
    person = (
        await session.execute(
            select(Person).where(Person.id == person_id, Person.owner_id == owner_id)
        )
    ).scalar_one_or_none()
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown person")
    return person


@router.get("", response_model=list[PersonOut])
async def list_people(
    auth: Annotated[AuthContext, Depends(get_auth)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[PersonOut]:
    rows = (
        await session.execute(
            select(Person, func.count(Face.id))
            .join(Face, Face.person_id == Person.id)
            .where(Person.owner_id == auth.user.id)
            .group_by(Person.id)
            .order_by(func.count(Face.id).desc())
        )
    ).all()

    out = []
    for person, face_count in rows:
        # Cover: the grid thumbnail of some photo containing this person.
        cover_asset_id = (
            await session.execute(
                select(Thumbnail.asset_id)
                .join(Face, Face.asset_id == Thumbnail.asset_id)
                .where(Face.person_id == person.id, Thumbnail.kind == "grid")
                .limit(1)
            )
        ).scalar_one_or_none()
        out.append(
            PersonOut(
                id=person.id,
                name=person.name,
                face_count=face_count,
                cover=sign_asset_url(cover_asset_id, "grid") if cover_asset_id else None,
            )
        )
    return out


@router.patch("/{person_id}", response_model=PersonOut)
async def rename_person(
    person_id: uuid.UUID,
    body: PersonRename,
    auth: Annotated[AuthContext, Depends(get_auth)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PersonOut:
    person = await _get_owned_person(session, auth.user.id, person_id)
    person.name = body.name
    await session.commit()
    face_count = (
        await session.scalar(select(func.count(Face.id)).where(Face.person_id == person.id))
    ) or 0
    return PersonOut(id=person.id, name=person.name, face_count=face_count, cover=None)


@router.post("/{person_id}/merge", status_code=status.HTTP_204_NO_CONTENT)
async def merge_people(
    person_id: uuid.UUID,
    body: PersonMerge,
    auth: Annotated[AuthContext, Depends(get_auth)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Move all faces from `other_id` into `person_id` and delete the former."""
    if person_id == body.other_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot merge a person into itself"
        )
    target = await _get_owned_person(session, auth.user.id, person_id)
    other = await _get_owned_person(session, auth.user.id, body.other_id)

    await session.execute(
        update(Face).where(Face.person_id == other.id).values(person_id=target.id)
    )
    await session.execute(delete(Person).where(Person.id == other.id))
    await session.commit()


@router.get("/{person_id}/assets")
async def person_assets(
    person_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(get_auth)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    from sqlalchemy.orm import selectinload

    from app.routers.assets import asset_to_out

    await _get_owned_person(session, auth.user.id, person_id)
    result = await session.execute(
        select(Asset)
        .join(Face, Face.asset_id == Asset.id)
        .where(Face.person_id == person_id, Asset.owner_id == auth.user.id)
        .options(selectinload(Asset.thumbnails))
        .order_by(Asset.taken_at.desc().nulls_last(), Asset.created_at.desc())
        .distinct()
    )
    return [asset_to_out(a) for a in result.scalars()]
