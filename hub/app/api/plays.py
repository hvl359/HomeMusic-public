"""Listening data for mixes and «Моя волна»: player events and «Не нравится» (see app/plays.py)."""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import plays
from app.api.schemas import DislikeIn, DislikeOut, PlayEventRejected, PlayEventsIn, PlayEventsOut
from app.auth import current_user
from app.db import get_session
from app.models import Dislike, PlayEvent, Track, User, utcnow

router = APIRouter(tags=["plays"])


@router.post("/api/plays/events", response_model=PlayEventsOut)
async def events(body: PlayEventsIn, user: User = Depends(current_user),
                 s: AsyncSession = Depends(get_session, scope="function")):
    if body.expected_user_id is not None and body.expected_user_id != user.id:
        raise HTTPException(409, "Listening events belong to another account")
    r = await plays.record_events(s, user.id, body.events)
    # a catalog track the app played from its precache never asked the stream as a listen: its `start` is one
    # (a track of an economy import is downloaded once listened to)
    refs = {e.get("ref") for e in body.events if isinstance(e, dict) and e.get("kind") == "start"}
    if refs := sorted(r for r in refs if isinstance(r, str) and r and not r.startswith("nd:")):
        from app.imports.core import listened

        await s.commit()
        for ref in refs:
            await listened(user.id, ref)
    return PlayEventsOut(accepted=r.accepted, duplicates=r.duplicates,
                         rejected=[PlayEventRejected(**x) for x in r.rejected])


@router.get("/api/plays/summary")
async def listening_summary(start: date, end: date, timezone: str = "UTC", user: User = Depends(current_user),
                            s: AsyncSession = Depends(get_session, scope="function")):
    from app.listening_summary import summary

    if end < start or (end - start).days > 3660 or end == date.max:
        raise HTTPException(422, "Invalid listening period")
    try:
        return await summary(s, user.id, start, end, timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, "Unknown timezone") from None


def _out(d: Dislike) -> DislikeOut:
    return DislikeOut(id=d.id, ref=d.ref, nd_song_id=d.nd_song_id, artist_ref=d.artist_ref, artist=d.artist,
                      title=d.title, source=d.source, created_at=d.created_at)


@router.get("/api/dislikes", response_model=list[DislikeOut])
async def list_dislikes(user: User = Depends(current_user), s: AsyncSession = Depends(get_session, scope="function")):
    rows = (await s.execute(select(Dislike).where(Dislike.user_id == user.id)
                            .order_by(Dislike.created_at.desc(), Dislike.id.desc()))).scalars()
    return [_out(d) for d in rows]


@router.post("/api/dislikes", response_model=DislikeOut)
async def add(body: DislikeIn, user: User = Depends(current_user),
              s: AsyncSession = Depends(get_session, scope="function")):
    d = await plays.add_dislike(s, user.id, ref=body.ref, nd_song_id=body.nd_song_id, artist_ref=body.artist_ref,
                                artist=body.artist, title=body.title, source=plays.dislike_source(body.client))
    assert d is not None
    await plays.dislike_event(s, user.id, "dislike", ref=d.artist_ref or d.ref, nd_song_id=d.nd_song_id,
                              client=body.client, context=body.context,
                              target_type="artist" if d.artist_ref else "track")
    return _out(d)


@router.delete("/api/dislikes")
async def remove(ref: str | None = None, nd_song_id: str | None = None, artist_ref: str | None = None,
                 client: str = "pwa", user: User = Depends(current_user),
                 s: AsyncSession = Depends(get_session, scope="function")):
    """«Не нравится» off: the track (`ref` and/or `nd_song_id`) or the artist (`artist_ref`)."""
    if not (ref or nd_song_id or artist_ref):
        raise HTTPException(400, "Укажите трек или исполнителя")
    n = await plays.remove_dislikes(s, user.id, ref=ref, nd_song_id=nd_song_id, artist_ref=artist_ref)
    if n:
        await plays.dislike_event(s, user.id, "undislike", ref=artist_ref or ref, nd_song_id=nd_song_id,
                                  client=client[:32], target_type="artist" if artist_ref else "track")
    return {"removed": n}


@router.delete("/api/dislikes/{dislike_id}")
async def remove_one(dislike_id: int, user: User = Depends(current_user),
                     s: AsyncSession = Depends(get_session, scope="function")):
    d = await s.get(Dislike, dislike_id)
    if d is None or d.user_id != user.id:
        raise HTTPException(404, "Не найдено")
    await plays.dislike_event(s, user.id, "undislike", ref=d.artist_ref or d.ref, nd_song_id=d.nd_song_id,
                              client="pwa", target_type="artist" if d.artist_ref else "track")
    await s.delete(d)
    return {"removed": 1}


@router.get("/api/plays/history")
async def listening_history(response: Response, limit: int = Query(50, ge=1, le=100),
                            offset: int = Query(0, ge=0, le=100000),
                            user: User = Depends(current_user),
                            s: AsyncSession = Depends(get_session, scope="function")):
    """Personal playback attempts, newest first; checkpoints are not separate listens."""
    response.headers["Cache-Control"] = "no-store"
    grouped = (PlayEvent.playback_id.is_not(None) & PlayEvent.device_id.is_not(None))
    ranked = select(PlayEvent.id.label("id"), func.row_number().over(
        partition_by=(case((grouped, PlayEvent.device_id)),
                      case((grouped, PlayEvent.playback_id)),
                      case((~grouped, PlayEvent.id))),
        order_by=(PlayEvent.ts.desc(), PlayEvent.id.desc())).label("rank")).where(
            PlayEvent.user_id == user.id, PlayEvent.target_type == "track",
            PlayEvent.kind.in_(("start", "progress", "skip", "finish", "interrupted", "error")),
            PlayEvent.superseded_scrobble.is_(False), PlayEvent.ts <= utcnow()).subquery()
    rows = list((await s.execute(select(PlayEvent).join(ranked, ranked.c.id == PlayEvent.id)
        .where(ranked.c.rank == 1).order_by(PlayEvent.ts.desc(), PlayEvent.id.desc())
        .offset(offset).limit(limit + 1))).scalars())
    ids = {r.nd_song_id for r in rows if r.nd_song_id}
    tracks = {t.nd_song_id: t for t in (await s.execute(select(Track).where(
        Track.nd_song_id.in_(ids)).order_by(Track.id))).scalars()} if ids else {}
    items = []
    for row in rows[:limit]:
        meta = row.track_metadata or {}
        track = tracks.get(row.nd_song_id)
        artists = meta.get("artists") or []
        artist = ", ".join(a["name"] for a in artists if a.get("name"))
        items.append({"id": row.id, "ts": row.ts.isoformat() + "Z", "kind": row.kind, "client": row.client,
                      "ref": row.ref, "nd_song_id": row.nd_song_id,
                      "title": meta.get("title") or (track.title if track else None),
                      "artist": artist or (track.artist if track else None),
                      "duration_s": row.duration_s or (track.duration_s if track else None),
                      "listened_ms": row.listened_ms})
    return {"items": items, "next_offset": offset + limit if len(rows) > limit else None}
