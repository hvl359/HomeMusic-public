# Personal listening history

The web/PWA interface now includes **Ещё → История прослушивания** (`#/history`).
Each signed-in user sees only their own playback attempts, newest first, with local date/time,
status, measured listening time when available, and a button to play the track again.
Repeated plays remain separate. Checkpoints sharing a device/playback ID become one entry.
Older events without playback IDs remain separate evidence; no grouping is guessed for them.
Likes, dislikes, future timestamps and superseded Navidrome scrobbles are excluded.
A started, skipped or interrupted attempt is not presented as a completed listen.

`GET /api/plays/history?limit=50&offset=0` requires the current user session and returns
`{items, next_offset}`. Limit: 1–100; offset: 0–100000. Responses use `Cache-Control: no-store`.
Existing playback-event storage is reused, so no database migration is needed.
Metadata comes from the saved event, with the local library as a fallback. Unknown tracks
remain visible; replay is disabled if neither a catalog reference nor a library ID exists.
Pagination is live: use Refresh if playback continues while browsing older pages.
Navidrome-only plays appear after the existing background scrobble sync (up to one hour).

This change does not add a native Android screen, modify server configuration, or deploy
anything automatically. Build/deploy both the Hub API and web frontend together using the
existing deployment procedure and backups. The native app may access the web route where
it exposes the embedded More screen; its native home screen is unchanged.

Checks:

```bash
cd web
npm ci
npm run build
cd ../hub
pytest tests/test_plays.py -q
```
