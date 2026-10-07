# SONORA

SONORA is a static music player designed for GitHub Pages. It is intentionally minimal, production-ready, and optimized for a dark neon aesthetic.

## What changed

- Simplified the site to a clean, production-ready listening experience.
- Removed non-player sections and extra noise from the interface.
- Kept the design focused on a Spotify-style library and player flow.
- Music is stored in the repository under `audio/` and can be added automatically through `audio/manifest.json`.
- A Telegram-based sync workflow can poll a Telegram group and add new tracks to the repo automatically.

## Run locally

```bash
python3 -m http.server 8080
```

Then open:

```text
http://localhost:8080
```

## Add music

1. Place an MP3 inside `audio/`.
2. Add one entry to `audio/manifest.json`.
3. Commit and push.

Example manifest item:

```json
{
  "id": "night-shift",
  "file": "audio/night-shift.mp3",
  "title": "Night Shift",
  "artist": "Aster Vale",
  "album": "Afterglow",
  "year": 2026,
  "genre": "Electronic",
  "duration": "03:42",
  "cover": ""
}
```

## Telegram sync automation

The repo includes a GitHub Actions workflow and helper script for polling a Telegram group and importing new audio files.

Required GitHub repository secrets:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

The workflow runs on a schedule and uses `getUpdates` with saved offset tracking. It downloads new audio files, converts them to MP3 with FFmpeg when needed, updates `audio/manifest.json`, and commits the result back to the repository.

Duplicate protection is three-layered:

1. Telegram `file_unique_id` is remembered in `.telegram-sync-state.json` and rejected on sight.
2. Every file's SHA-256 is compared against `audio/manifest.json`, so re-sent bytes are rejected even with a new Telegram id.
3. Track ids and file names are made unique (slug plus content hash), so two imports in the same second never overwrite each other.

Notes for the automation:

- The Telegram bot must be able to read group messages: disable privacy mode (`/setprivacy` in BotFather) or promote the bot to admin in the group.
- The Bot API only returns messages sent *after* the first successful poll; older messages cannot be imported.
- State is committed together with the audio, so the daily runs keep their offset and dedup history across runs.

## Notes

- The app works without any backend or build step.
- The theme uses a neon cyan and purple palette on a deep dark background.
- Compression guidance: MP3 VBR `-q:a 2` is the default operational target for low-size, near-transparent quality.
