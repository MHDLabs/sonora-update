#!/usr/bin/env python3
"""Import new audio/MP3 files from Telegram (private chat, group, or channel)
into the repository.

Strategy:
- Poll Telegram getUpdates with a persistent offset stored in the repo.
- Accept updates from ANY chat unless TELEGRAM_CHAT_ID is set as a filter.
- Import audio / voice / video_note / document (MP3 & other audio mime types).
- Deduplicate: file_unique_id + sha256 content hash + manifest id.
- Convert non-MP3 sources to MP3 with ffmpeg (VBR -q:a 2).
- Read duration with ffprobe and write it into the manifest.
- Commit audio + manifest + sync state back to the repository.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
AUDIO_DIR = ROOT / 'audio'
MANIFEST_PATH = AUDIO_DIR / 'manifest.json'
STATE_PATH = ROOT / '.telegram-sync-state.json'
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
# Optional. If empty, updates from ANY chat (private, group, channel) are accepted.
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
API = f'https://api.telegram.org/bot{BOT_TOKEN}' if BOT_TOKEN else ''
MAX_FILE_IDS = 5000
REQUEST_TIMEOUT = 90
GETUPDATES_TIMEOUT = 25          # long-poll seconds (must be < REQUEST_TIMEOUT)
AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.aac', '.ogg', '.oga', '.opus', '.flac', '.wav', '.wma'}


def log(message):
    print(message, flush=True)


def ensure_audio_dir():
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def cleanup_tmp_files():
    """Remove leftovers from crashed runs so they don't pile up in the repo."""
    for p in AUDIO_DIR.glob('*.tmp'):
        try:
            p.unlink()
            log(f'Cleaned leftover tmp file: {p.name}')
        except OSError:
            pass


# ---------------------------------------------------------------- state


def load_state():
    if not STATE_PATH.exists():
        return {'offset': 0, 'file_ids': [], 'imported': 0}
    try:
        data = json.loads(STATE_PATH.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return {'offset': 0, 'file_ids': [], 'imported': 0}
    if not isinstance(data, dict):
        return {'offset': 0, 'file_ids': [], 'imported': 0}
    try:
        data['offset'] = int(data.get('offset', 0) or 0)
    except (TypeError, ValueError):
        data['offset'] = 0
    if not isinstance(data.get('file_ids'), list):
        data['file_ids'] = []
    try:
        data['imported'] = int(data.get('imported', 0) or 0)
    except (TypeError, ValueError):
        data['imported'] = 0
    return data


def save_state(state):
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )


def remember_file_id(state, file_id):
    ids = [f for f in state.get('file_ids', []) if f != file_id]
    ids.append(file_id)
    state['file_ids'] = ids[-MAX_FILE_IDS:]


def read_manifest():
    if not MANIFEST_PATH.exists():
        return {'tracks': []}
    try:
        with MANIFEST_PATH.open('r', encoding='utf-8') as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get('tracks'), list):
            return data
    except Exception:
        pass
    return {'tracks': []}


def write_manifest(data):
    with MANIFEST_PATH.open('w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write('\n')


def manifest_hashes(manifest):
    return {
        str(item.get('sha256', '')).lower()
        for item in manifest.get('tracks', [])
        if item.get('sha256')
    }


def manifest_ids(manifest):
    return {
        str(item.get('id', '')).lower()
        for item in manifest.get('tracks', [])
        if item.get('id')
    }


def unique_track_id(base, taken, digest):
    candidate = base or 'untitled-track'
    if candidate not in taken:
        return candidate
    return f'{candidate}-{digest[:6]}'


def slugify(text, fallback='untitled-track'):
    cleaned = re.sub(r'[^0-9A-Za-z]+', '-', (text or '').strip()).strip('-').lower()
    cleaned = re.sub(r'-{2,}', '-', cleaned)
    return (cleaned or fallback)[:70]


def sha256_of(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def ffprobe_duration(path):
    try:
        proc = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
            check=True, capture_output=True, text=True, timeout=60,
        )
        seconds = float(proc.stdout.strip())
    except Exception:
        return '00:00'
    total = max(0, int(seconds))
    return f'{total // 60:02d}:{total % 60:02d}'


def download_file(file_path, url):
    with requests.get(url, timeout=REQUEST_TIMEOUT, stream=True) as resp:
        resp.raise_for_status()
        with open(file_path, 'wb') as fh:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                if chunk:
                    fh.write(chunk)


def api_request(method, params=None, timeout=REQUEST_TIMEOUT):
    resp = requests.get(f'{API}/{method}', params=params or {}, timeout=timeout)
    try:
        payload = resp.json()
    except ValueError:
        raise RuntimeError(f'Telegram API {method} returned non-JSON (HTTP {resp.status_code})')
    if not payload.get('ok'):
        raise RuntimeError(
            f'Telegram API {method} failed (HTTP {resp.status_code}): {payload.get("description")}'
        )
    return payload


def delete_webhook():
    """getUpdates does not work while a webhook is set. Clear it."""
    try:
        api_request('deleteWebhook', {'drop_pending_updates': 'false'})
        log('Webhook cleared (getUpdates is now allowed).')
    except Exception as exc:
        log(f'Warning: could not clear webhook: {exc}')


def is_mp3_bytes(path):
    try:
        with Path(path).open('rb') as fh:
            head = fh.read(3)
            if head == b'ID3':
                return True
            fh.seek(0)
            first = fh.read(2)
        return len(first) == 2 and first[0] == 0xFF and (first[1] & 0xE0) == 0xE0
    except OSError:
        return False


def ensure_mp3(source_path, dest_path):
    """Keep MP3 sources as-is; re-encode everything else to MP3 VBR -q:a 2."""
    if is_mp3_bytes(source_path):
        if Path(source_path) != Path(dest_path):
            source_path.replace(dest_path)
        return
    cmd = [
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
        '-i', str(source_path), '-vn',
        '-acodec', 'libmp3lame', '-q:a', '2', str(dest_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600)
    source_path.unlink(missing_ok=True)


def get_audio_url(file_id):
    data = api_request('getFile', {'file_id': file_id})
    file_path = data.get('result', {}).get('file_path')
    if not file_path:
        raise RuntimeError('No file_path in Telegram response')
    return f'https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}'


def fetch_updates(offset):
    """Fetch raw updates. Does NOT advance offset — caller decides when it's safe."""
    try:
        data = api_request(
            'getUpdates',
            {
                'offset': offset,
                'limit': 100,
                'timeout': GETUPDATES_TIMEOUT,
                'allowed_updates': json.dumps(
                    ['message', 'edited_message', 'channel_post', 'edited_channel_post']
                ),
            },
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as exc:
        log(f'getUpdates failed: {exc}')
        return []
    return data.get('result', [])


def pick_audio(message):
    """Return (audio_object, source_hint) or (None, None).

    Accepts:
      - audio           (music sent as audio)
      - voice           (voice message)
      - video_note      (round video)
      - document        (.mp3 or any audio/* mime, checked by extension too)
    """
    for key in ('audio', 'voice', 'video_note'):
        node = message.get(key)
        if isinstance(node, dict) and node.get('file_id'):
            return node, key

    doc = message.get('document')
    if isinstance(doc, dict) and doc.get('file_id'):
        mime = str(doc.get('mime_type', '')).lower()
        name = str(doc.get('file_name', '')).lower()
        ext = Path(name).suffix
        if mime.startswith('audio/') or ext in AUDIO_EXTENSIONS:
            return doc, 'document'
    return None, None


def build_title(message, audio):
    caption = (message.get('caption') or '').strip().splitlines()
    if caption:
        for line in caption:
            text = line.strip()
            if text:
                return text[:120]
    title = (audio.get('title') or '').strip()
    if title:
        return title[:120]
    fname = (audio.get('file_name') or '').strip()
    if fname:
        return Path(fname).stem[:120]
    return 'Untitled track'


def chat_matches(message):
    """If CHAT_ID is set, only accept that chat. Otherwise accept everything."""
    if not CHAT_ID:
        return True
    chat = message.get('chat') or {}
    return str(chat.get('id')) == str(CHAT_ID)


def import_update(item, state, manifest):
    """Import one update. Returns True when a new track was added."""
    message = (
        item.get('message')
        or item.get('edited_message')
        or item.get('channel_post')
        or item.get('edited_channel_post')
    )
    if not isinstance(message, dict):
        return False

    if not chat_matches(message):
        return False

    audio, source_hint = pick_audio(message)
    if not audio:
        return False

    file_id = str(audio.get('file_id', ''))
    file_unique_id = str(audio.get('file_unique_id', ''))
    if not file_id:
        return False

    if file_unique_id and file_unique_id in set(state.get('file_ids', [])):
        log(f'Skip duplicate file_unique_id={file_unique_id}')
        return False

    # Telegram Bot API download limit is 20 MB
    file_size = int(audio.get('file_size') or 0)
    if file_size and file_size > 20 * 1024 * 1024:
        log(f'Skip oversized file ({file_size} bytes > 20MB): {file_id}')
        if file_unique_id:
            remember_file_id(state, file_unique_id)
        return False

    title = build_title(message, audio)
    slug = slugify(title)
    stamp = int(time.time())
    raw_path = AUDIO_DIR / f'{slug}-{stamp}-{file_unique_id or file_id}.tmp'

    try:
        url = get_audio_url(file_id)
        download_file(raw_path, url)
    except Exception as exc:
        log(f'Download failed for file_id={file_id}: {exc}')
        raw_path.unlink(missing_ok=True)
        # Do NOT remember this file id so we can retry next run
        return False

    content_hash = sha256_of(raw_path)
    if content_hash in manifest_hashes(manifest):
        raw_path.unlink(missing_ok=True)
        log(f'Skip duplicate content sha256={content_hash[:12]} title={title!r}')
        if file_unique_id:
            remember_file_id(state, file_unique_id)
        return False

    final_path = AUDIO_DIR / f'{slug}-{stamp}-{content_hash[:8]}.mp3'
    if final_path.exists():
        final_path = AUDIO_DIR / f'{slug}-{stamp}-{content_hash[:8]}-{file_unique_id or file_id}.mp3'

    try:
        ensure_mp3(raw_path, final_path)
    except subprocess.CalledProcessError as exc:
        log(f'ffmpeg failed for {raw_path.name}: {exc.stderr or exc}')
        raw_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        return False

    if raw_path.exists() and raw_path != final_path:
        raw_path.unlink(missing_ok=True)

    final_hash = sha256_of(final_path) if final_path.exists() else content_hash
    if final_hash in manifest_hashes(manifest):
        final_path.unlink(missing_ok=True)
        log(f'Skip duplicate converted content sha256={final_hash[:12]}')
        if file_unique_id:
            remember_file_id(state, file_unique_id)
        return False

    duration = ffprobe_duration(final_path)
    track_id = unique_track_id(slug, manifest_ids(manifest), final_hash)
    track = {
        'id': track_id,
        'file': f'audio/{final_path.name}',
        'title': title,
        'artist': (audio.get('performer') or '').strip() or 'Telegram import',
        'album': 'Imported',
        'year': int(time.strftime('%Y')),
        'duration': duration,
        'cover': '',
        'sha256': final_hash,
        'telegram_file_unique_id': file_unique_id,
        'source': source_hint,
        'imported_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }

    manifest.setdefault('tracks', []).append(track)
    write_manifest(manifest)
    if file_unique_id:
        remember_file_id(state, file_unique_id)
    state['imported'] = int(state.get('imported', 0)) + 1
    log(f'Imported {track_id} ({duration}) from {source_hint} -> {final_path.name}')
    return True


def handle_updates():
    ensure_audio_dir()
    cleanup_tmp_files()

    if not BOT_TOKEN:
        log('ERROR: TELEGRAM_BOT_TOKEN is not set. Aborting.')
        return 0
    if not API:
        log('ERROR: API base URL is empty. Aborting.')
        return 0

    delete_webhook()

    state = load_state()
    manifest = read_manifest()
    log(f'Starting sync: offset={state.get("offset")} '
        f'chat_filter={CHAT_ID or "(any chat)"} '
        f'imported_total={state.get("imported", 0)}')

    updates = fetch_updates(state.get('offset', 0))
    log(f'Received {len(updates)} update(s) from Telegram.')

    if not updates:
        save_state(state)
        return 0

    imported = 0
    max_update_id = state.get('offset', 0)
    any_fatal = False

    for item in updates:
        update_id = int(item.get('update_id', 0))
        try:
            if import_update(item, state, manifest):
                imported += 1
            # Only advance past updates we successfully handled
            if update_id >= max_update_id:
                max_update_id = update_id + 1
        except Exception as exc:
            log(f'ERROR processing update_id={update_id}: {exc}')
            log(traceback.format_exc())
            any_fatal = True
            # Stop advancing past this update so we can retry next run
            break

    if not any_fatal:
        state['offset'] = max_update_id
        log(f'Advanced offset to {state["offset"]}')

    save_state(state)
    return imported


def commit_changes(imported):
    # Nothing to do if state didn't even change
    subprocess.run(['git', 'config', 'user.name', 'github-actions[bot]'],
                   check=True, cwd=str(ROOT))
    subprocess.run(
        ['git', 'config', 'user.email',
         '41898282+github-actions[bot]@users.noreply.github.com'],
        check=True, cwd=str(ROOT),
    )

    subprocess.run(['git', 'add', 'audio', '.telegram-sync-state.json'],
                   check=True, cwd=str(ROOT))
    staged = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=str(ROOT))
    if staged.returncode == 0:
        log('Nothing staged to commit.')
        return

    msg = f'Add imported Telegram tracks ({imported})' if imported > 0 \
        else 'Update Telegram sync state'
    subprocess.run(['git', 'commit', '-m', msg], check=True, cwd=str(ROOT))

    # Pull latest before pushing to avoid non-fast-forward failures
    pull = subprocess.run(
        ['git', 'pull', '--rebase', '--autostash', 'origin', 'HEAD'],
        cwd=str(ROOT),
    )
    if pull.returncode != 0:
        log('Warning: git pull --rebase failed; attempting push anyway.')

    subprocess.run(['git', 'push'], check=True, cwd=str(ROOT))
    log(f'Pushed changes to repository (imported={imported}).')


def main():
    try:
        imported = handle_updates()
        commit_changes(imported)
    except Exception as exc:
        log(f'FATAL: {exc}')
        log(traceback.format_exc())
        sys.exit(1)


if __name__ == '__main__':
    main()
