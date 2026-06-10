"""Cluster face embeddings into people.

Greedy threshold clustering, chosen over DBSCAN-style re-clustering because
it is incremental: existing people (and the names the user gave them) are
stable across runs — new faces either join a known person or form new
clusters.
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.embedding import cosine_similarity, normalize
from app.models import Asset, Face, Person

logger = logging.getLogger(__name__)


@dataclass
class ClusterReport:
    assigned_to_existing: int = 0
    new_people: int = 0
    unassigned: int = 0


def _centroid(embeddings: list[list[float]]) -> list[float]:
    n = len(embeddings)
    summed = [sum(vals) / n for vals in zip(*embeddings, strict=True)]
    return normalize(summed)


async def cluster_faces(
    session: AsyncSession,
    owner_id: uuid.UUID,
    threshold: float,
    min_cluster_size: int,
) -> ClusterReport:
    report = ClusterReport()

    owned_faces = (
        select(Face).join(Asset, Face.asset_id == Asset.id).where(Asset.owner_id == owner_id)
    )

    unassigned = list(
        (
            await session.execute(
                owned_faces.where(Face.person_id.is_(None), Face.embedding.is_not(None))
            )
        ).scalars()
    )
    if not unassigned:
        return report

    # Centroids of existing people, from their current member faces.
    centroids: dict[uuid.UUID, list[float]] = {}
    assigned = (
        await session.execute(owned_faces.where(Face.person_id.is_not(None)))
    ).scalars()
    members: dict[uuid.UUID, list[list[float]]] = {}
    for face in assigned:
        members.setdefault(face.person_id, []).append(face.embedding)
    for person_id, embeddings in members.items():
        centroids[person_id] = _centroid(embeddings)

    # Pass 1: join an existing person when clearly the same face.
    leftover: list[Face] = []
    for face in unassigned:
        best_id, best_sim = None, threshold
        for person_id, centroid in centroids.items():
            sim = cosine_similarity(face.embedding, centroid)
            if sim >= best_sim:
                best_id, best_sim = person_id, sim
        if best_id is not None:
            face.person_id = best_id
            members[best_id].append(face.embedding)
            centroids[best_id] = _centroid(members[best_id])
            report.assigned_to_existing += 1
        else:
            leftover.append(face)

    # Pass 2: greedy-cluster the rest into new people.
    remaining = leftover
    while remaining:
        seed, rest = remaining[0], remaining[1:]
        group = [seed]
        others = []
        for face in rest:
            if cosine_similarity(face.embedding, seed.embedding) >= threshold:
                group.append(face)
            else:
                others.append(face)
        if len(group) >= min_cluster_size:
            person = Person(owner_id=owner_id)
            session.add(person)
            await session.flush()  # get person.id
            for face in group:
                face.person_id = person.id
            report.new_people += 1
        else:
            report.unassigned += len(group)
        remaining = others

    await session.commit()
    return report
