#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
AUDIO_DIR = ROOT / 'audio'
MANIFEST_PATH = AUDIO_DIR / 'manifest.json'
OFFSET_PATH = ROOT / '.telegram-offset'
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()


def ensure_audio_dir():
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)


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


def load_offset():
    if not OFFSET_PATH.exists():
        return 0
    try:
        return int(OFFSET_PATH.read_text(encoding='utf-8').strip() or '0')
    except Exception:
        return 0


def save_offset(value):
    OFFSET_PATH.write_text(str(value), encoding='utf-8')


def download_file(file_path, url):
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    with open(file_path, 'wb') as fh:
        fh.write(resp.content)


def ensure_mp3(source_path, dest_path):
    if source_path.suffix.lower() == '.mp3':
        source_path.replace(dest_path)
        return
    cmd = [
        'ffmpeg', '-y', '-i', str(source_path), '-vn', '-acodec', 'libmp3lame', '-q:a', '2', str(dest_path)
    ]
    subprocess.run(cmd, check=True)
    source_path.unlink(missing_ok=True)


def add_track_to_manifest(track):
    manifest = read_manifest()
    existing = manifest.get('tracks', [])
    for item in existing:
        if item.get('id') == track['id']:
            return
    existing.append(track)
    manifest['tracks'] = existing
    write_manifest(manifest)


def get_audio_url(bot_token, file_id):
    r = requests.get(f'https://api.telegram.org/bot{bot_token}/getFile', params={'file_id': file_id}, timeout=60)
    r.raise_for_status()
    data = r.json()
    file_path = data.get('result', {}).get('file_path')
    if not file_path:
        raise RuntimeError('No file_path in Telegram response')
    return f'https://api.telegram.org/file/bot{bot_token}/{file_path}'


def fetch_updates():
    if not BOT_TOKEN or not CHAT_ID:
        print('Skipping Telegram sync: missing BOT_TOKEN or CHAT_ID')
        return []

    offset = load_offset()
    r = requests.get(
        f'https://api.telegram.org/bot{BOT_TOKEN}/getUpdates',
        params={'offset': offset, 'limit': 100, 'timeout': 30},
        timeout=60,
    )
    r.raise_for_status()
    payload = r.json()
    result = payload.get('result', [])
    if not result:
        return []
    last_update_id = max(item.get('update_id', offset) for item in result)
    save_offset(last_update_id + 1)
    return result


def handle_updates():
    imported = []
    for item in fetch_updates():
        message = item.get('message') or item.get('edited_message')
        if not message:
            continue
        chat = message.get('chat') or {}
        if str(chat.get('id')) != str(CHAT_ID):
            continue
        audio = message.get('audio') or message.get('voice') or message.get('video_note')
        if not audio:
            continue
        file_id = audio.get('file_id')
        if not file_id:
            continue
        title = (message.get('caption') or audio.get('title') or 'Untitled track').strip()
        safe_title = ''.join(ch for ch in title if ch.isalnum() or ch in (' ', '-', '_')).strip() or 'untitled-track'
        safe_title = safe_title[:80]
        source_name = f'{safe_title}-{int(time.time())}'
        url = get_audio_url(BOT_TOKEN, file_id)
        raw_path = AUDIO_DIR / f'{source_name}.tmp'
        final_path = AUDIO_DIR / f'{source_name}.mp3'
        download_file(raw_path, url)
        ensure_mp3(raw_path, final_path)
        track = {
            'id': safe_title.lower().replace(' ', '-'),
            'file': f'audio/{final_path.name}',
            'title': safe_title,
            'artist': 'Telegram import',
            'album': 'Imported',
            'year': int(time.strftime('%Y')),
            'genre': 'Imported',
            'duration': '00:00',
            'cover': ''
        }
        add_track_to_manifest(track)
        imported.append(track)
    return imported


def commit_changes(imported):
    if not imported:
        print('No new music imported')
        return
    subprocess.run(['git', 'config', 'user.name', 'github-actions[bot]'], check=True, cwd=str(ROOT))
    subprocess.run(['git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com'], check=True, cwd=str(ROOT))
    subprocess.run(['git', 'add', 'audio'], check=True, cwd=str(ROOT))
    subprocess.run(['git', 'commit', '-m', f'Add imported Telegram tracks ({len(imported)})'], check=True, cwd=str(ROOT))
    subprocess.run(['git', 'push'], check=True, cwd=str(ROOT))


def main():
    ensure_audio_dir()
    imported = handle_updates()
    if imported:
        commit_changes(imported)
    else:
        print('No new tracks detected')


if __name__ == '__main__':
    main()
