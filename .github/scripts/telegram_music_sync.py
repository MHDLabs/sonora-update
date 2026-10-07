#!/usr/bin/env python3
"""Import new audio files from a Telegram group into the repository.

Strategy:
- Poll Telegram getUpdates with a persistent offset (stored in the repo).
- Import audio / voice / video_note / audio-document messages.
- Deduplicate three ways: file_unique_id, sha256 content hash, manifest id.
- Convert non-MP3 sources to MP3 with ffmpeg (VBR -q:a 2).
- Read duration with ffprobe and write it into the manifest.
- Commit audio + manifest + sync state back to the repository.
"""
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
AUDIO_DIR = ROOT / 'audio'
MANIFEST_PATH = AUDIO_DIR / 'manifest.json'
STATE_PATH = ROOT / '.telegram-sync-state.json'
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
API = f'https://api.telegram.org/bot{BOT_TOKEN}' if BOT_TOKEN else ''
MAX_FILE_IDS = 5000
REQUEST_TIMEOUT = 90


def log(message):
    print(message, flush=True)


def ensure_audio_dir():
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- state


def load_state():
    """Persistent offset + processed-file bookkeeping, committed with the repo."""
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
    """Return MM:SS duration via ffprobe, or 00:00 when unavailable."""
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
    resp = requests.get(url, timeout=REQUEST_TIMEOUT, stream=True)
    resp.raise_for_status()
    with open(file_path, 'wb') as fh:
        for chunk in resp.iter_content(chunk_size=1024 * 256):
            if chunk:
                fh.write(chunk)


def api_request(method, params):
    resp = requests.get(f'{API}/{method}', params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get('ok'):
        raise RuntimeError(f'Telegram API {method} failed: {payload.get("description")}')
    return payload


def is_mp3_bytes(path):
    """Detect MP3 by magic bytes: raw downloads always end with .tmp."""
    try:
        with Path(path).open('rb') as fh:
            head = fh.read(3)
            if head == b'ID3':
                return True
            fh.seek(0)
            first = fh.read(2)
        # MPEG frame sync: 11 set bits
        return len(first) == 2 and first[0] == 0xFF and (first[1] & 0xE0) == 0xE0
    except OSError:
        return False


def ensure_mp3(source_path, dest_path):
    """Keep MP3 sources as-is (no quality loss); re-encode everything else to MP3 VBR -q:a 2."""
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


def fetch_updates(state):
    if not BOT_TOKEN or not CHAT_ID:
        log('Skipping Telegram sync: missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID')
        return []

    data = api_request('getUpdates', {
        'offset': state.get('offset', 0),
        'limit': 100,
        'timeout': 30,
        'allowed_updates': ['message'],
    })
    result = data.get('result', [])
    if result:
        state['offset'] = max(int(item.get('update_id', 0)) for item in result) + 1
    return result


def pick_audio(message):
    """Return (audio_object, source_hint) or (None, None)."""
    for key in ('audio', 'voice', 'video_note'):
        node = message.get(key)
        if isinstance(node, dict) and node.get('file_id'):
            return node, key
    doc = message.get('document')
    if isinstance(doc, dict) and str(doc.get('mime_type', '')).startswith('audio/'):
        if doc.get('file_id'):
            return doc, 'document'
    return None, None


def build_title(message, audio):
    caption = (message.get('caption') or '').strip().splitlines()
    if caption:
        for line in caption:
            text = line.strip()
            if text:
                return text[:120]
    return (audio.get('title') or '').strip() or 'Untitled track'


def import_update(item, state, manifest):
    """Import one update. Returns True when a new track was added."""
    message = item.get('message') or item.get('edited_message')
    if not isinstance(message, dict):
        return False

    chat = message.get('chat') or {}
    if str(chat.get('id')) != str(CHAT_ID):
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

    title = build_title(message, audio)
    slug = slugify(title)
    stamp = int(time.time())
    raw_path = AUDIO_DIR / f'{slug}-{stamp}-{file_unique_id or file_id}.tmp'

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    url = get_audio_url(file_id)
    download_file(raw_path, url)

    content_hash = sha256_of(raw_path)
    if content_hash in manifest_hashes(manifest):
        Path(raw_path).unlink(missing_ok=True)
        log(f'Skip duplicate content sha256={content_hash[:12]} title={title!r}')
        if file_unique_id:
            remember_file_id(state, file_unique_id)
        return False

    # name the final file with the content hash so two imports in the same
    # second can never overwrite each other
    final_path = AUDIO_DIR / f'{slug}-{stamp}-{content_hash[:8]}.mp3'
    if final_path.exists():
        final_path = AUDIO_DIR / f'{slug}-{stamp}-{content_hash[:8]}-{file_unique_id or file_id}.mp3'
    ensure_mp3(raw_path, final_path)
    # ensure_mp3 moves MP3 sources in place; re-encode leaves the .tmp behind
    if Path(raw_path).exists() and Path(raw_path) != Path(final_path):
        Path(raw_path).unlink(missing_ok=True)
    final_hash = sha256_of(final_path) if Path(final_path).exists() else content_hash
    if final_hash in manifest_hashes(manifest):
        Path(final_path).unlink(missing_ok=True)
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
        'genre': (audio.get('genre') or '').strip() or 'Imported',
        'duration': duration,
        'cover': '',
        'sha256': final_hash,
        'telegram_file_unique_id': file_unique_id,
        'imported_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }

    manifest.setdefault('tracks', []).append(track)
    write_manifest(manifest)
    if file_unique_id:
        remember_file_id(state, file_unique_id)
    state['imported'] = int(state.get('imported', 0)) + 1
    log(f'Imported {track_id} ({duration}) -> {final_path.name}')
    return True


def handle_updates():
    ensure_audio_dir()
    state = load_state()
    manifest = read_manifest()
    updates = fetch_updates(state)
    imported = 0
    for item in updates:
        try:
            if import_update(item, state, manifest):
                imported += 1
        except Exception as exc:
            log(f'Failed to import update_id={item.get("update_id")}: {exc}')
    save_state(state)
    return imported


def commit_changes(imported):
    if imported <= 0:
        log('No new tracks detected')
        return
    subprocess.run(['git', 'config', 'user.name', 'github-actions[bot]'], check=True, cwd=str(ROOT))
    subprocess.run(['git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com'], check=True, cwd=str(ROOT))
    subprocess.run(['git', 'add', 'audio', '.telegram-sync-state.json'], check=True, cwd=str(ROOT))
    staged = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=str(ROOT))
    if staged.returncode == 0:
        log('Nothing staged to commit')
        return
    subprocess.run(['git', 'commit', '-m', f'Add imported Telegram tracks ({imported})'], check=True, cwd=str(ROOT))
    subprocess.run(['git', 'push'], check=True, cwd=str(ROOT))


def main():
    imported = handle_updates()
    commit_changes(imported)


if __name__ == '__main__':
    main()
