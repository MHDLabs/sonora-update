#!/usr/bin/env python3
"""SONORA — add music to the library.

Usage:
    python .github/scripts/add_music.py          # scan /audio, extract covers, rebuild manifest
    python .github/scripts/add_music.py --check  # report only, write nothing;
                                                 # exit 0 = manifest up to date,
                                                 # exit 1 = drift (new/changed/missing files)

What it does:
  1. Scans every audio file in /audio (mp3, m4a, ogg, flac, wav).
  2. Reads ID3/Tags: title, artist, album, year, genre and embedded cover art.
  3. Extracts embedded artwork to audio/covers/<id>.<ext>.
  4. Reads duration (ffprobe when available, MPEG header estimate otherwise).
  5. Rebuilds audio/manifest.json — preserving hand-added fields (sha256,
     telegram_*, source, imported_at) and dropping entries whose file is gone.

Drop a file into /audio, run this script, commit. No JS/HTML edits needed.
"""

import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

# This file lives in .github/scripts/ — the project root is two levels up.
ROOT = Path(__file__).resolve().parents[2]
AUDIO_DIR = ROOT / 'audio'
COVERS_DIR = AUDIO_DIR / 'covers'
MANIFEST_PATH = AUDIO_DIR / 'manifest.json'
AUDIO_EXTS = {'.mp3', '.m4a', '.aac', '.ogg', '.oga', '.opus', '.flac', '.wav'}
ID = re.compile(r'[^0-9A-Za-z]+')

# --------------------------------------------------------------- id3 parsing


def syncsafe(b):
    return (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]


def decode_text(enc, raw):
    if not raw:
        return ''
    try:
        if enc == 0:
            return raw.decode('latin-1')
        if enc == 1:
            if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
                return raw.decode('utf-16')
            return raw.decode('utf-16-le')
        if enc == 2:
            return raw.decode('utf-16-be')
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('latin-1', 'replace')


def split_terminated(raw, enc, size=1):
    """Split raw at the first terminator (1 byte, or 2 bytes for UTF-16)."""
    if enc in (1, 2):
        for i in range(0, len(raw) - 1, 2):
            if raw[i] == 0 and raw[i + 1] == 0:
                return raw[:i], raw[i + 2:]
        return raw, b''
    idx = raw.find(b'\x00')
    if idx < 0:
        return raw, b''
    return raw[:idx], raw[idx + 1:]


def read_id3(path):
    """Return dict: title, artist, album, year, genre, cover(bytes), cover_mime."""
    out = {'title': '', 'artist': '', 'album': '', 'year': '', 'genre': '',
           'cover': None, 'cover_mime': 'image/jpeg'}
    with open(path, 'rb') as fh:
        head = fh.read(10)
        if len(head) == 10 and head[:3] == b'ID3':
            major = head[3]
            flags = head[5]
            size = syncsafe(head[6:10])
            tag = fh.read(size)
            if flags & 0x40:  # extended header
                if major == 4:
                    ext = syncsafe(tag[:4])
                else:
                    ext = struct.unpack('>I', tag[:4])[0] + 4
                tag = tag[ext:]
            pos, end = 0, len(tag)
            four = major != 2
            while pos + (10 if four else 6) <= end:
                if tag[pos] == 0:
                    break
                if four:
                    fid = tag[pos:pos + 4].decode('latin-1')
                    if major == 4:
                        fs = syncsafe(tag[pos + 4:pos + 8])
                    else:
                        fs = struct.unpack('>I', tag[pos + 4:pos + 8])[0]
                    hdr = 10
                else:
                    fid = tag[pos:pos + 3].decode('latin-1')
                    fs = struct.unpack('>I', b'\x00' + tag[pos + 3:pos + 6])[0]
                    hdr = 6
                if fs <= 0 or pos + hdr + fs > end:
                    break
                body = tag[pos + hdr:pos + hdr + fs]
                pos += hdr + fs
                if fid in ('TIT2', 'TT2'):
                    out['title'] = decode_text(body[0], body[1:]).strip(' \x00')
                elif fid in ('TPE1', 'TP1'):
                    out['artist'] = decode_text(body[0], body[1:]).strip(' \x00')
                elif fid in ('TALB', 'TAL'):
                    out['album'] = decode_text(body[0], body[1:]).strip(' \x00')
                elif fid in ('TYER', 'TDRC', 'TYE'):
                    out['year'] = decode_text(body[0], body[1:]).strip(' \x00')[:4]
                elif fid in ('TCON', 'TCO'):
                    g = decode_text(body[0], body[1:]).strip(' \x00')
                    out['genre'] = re.sub(r'^\(\d+\)', '', g).strip()
                elif fid in ('APIC', 'PIC'):
                    enc = body[0]
                    if fid == 'PIC':
                        rest = body[1:]
                        mime = {'JPG': 'image/jpeg', 'PNG': 'image/png',
                                'GIF': 'image/gif'}.get(
                                    rest[:3].decode('latin-1', 'replace').upper(),
                                    'image/jpeg')
                        rest = rest[3:]
                    else:
                        rest = body[1:]
                        mime_b, rest = split_terminated(rest, 0)
                        mime = mime_b.decode('latin-1') or 'image/jpeg'
                    rest = rest[1:]  # picture type byte
                    _, rest = split_terminated(rest, enc)  # picture description
                    if rest and not out['cover']:
                        out['cover'] = rest
                        out['cover_mime'] = mime
        elif len(head) >= 3:
            # No ID3v2 — try ID3v1 trailer
            fh.seek(-128, os.SEEK_END)
            v1 = fh.read(128)
            if v1[:3] == b'TAG':
                out['title'] = v1[3:33].rstrip(b'\x00 ').decode('latin-1')
                out['artist'] = v1[33:63].rstrip(b'\x00 ').decode('latin-1')
                out['album'] = v1[63:93].rstrip(b'\x00 ').decode('latin-1')
                out['year'] = v1[93:97].rstrip(b'\x00 ').decode('latin-1')
                if v1[127] != 255:
                    out['genre'] = ID3V1_GENRES.get(v1[127], '')
    return out


ID3V1_GENRES = {
    0: 'Blues', 1: 'Classic Rock', 2: 'Country', 3: 'Dance', 4: 'Disco',
    5: 'Funk', 6: 'Grunge', 7: 'Hip-Hop', 8: 'Jazz', 9: 'Metal',
    10: 'New Age', 11: 'Oldies', 12: 'Other', 13: 'Pop', 14: 'R&B',
    15: 'Rap', 16: 'Reggae', 17: 'Rock', 18: 'Techno', 19: 'Industrial',
    20: 'Alternative', 21: 'Ska', 22: 'Death Metal', 23: 'Pranks',
    24: 'Soundtrack', 25: 'Euro-Techno', 26: 'Ambient', 27: 'Trip-Hop',
    28: 'Vocal', 29: 'Jazz+Funk', 30: 'Fusion', 31: 'Trance',
    32: 'Classical', 33: 'Instrumental', 34: 'Acid', 35: 'House',
    36: 'Game', 37: 'Sound Clip', 38: 'Gospel', 39: 'Noise', 40: 'Alt. Rock',
    41: 'Bass', 42: 'Soul', 43: 'Punk', 44: 'Space', 45: 'Meditative',
    46: 'Instrumental Pop', 47: 'Instrumental Rock', 48: 'Ethnic',
    49: 'Gothic', 50: 'Darkwave', 51: 'Techno-Industrial', 52: 'Electronic',
    53: 'Pop-Folk', 54: 'Eurodance', 55: 'Dream', 56: 'Southern Rock',
    57: 'Comedy', 58: 'Cult', 59: 'Gangsta', 60: 'Top 40',
    61: 'Christian Rap', 62: 'Pop/Funk', 63: 'Jungle', 64: 'Native American',
    65: 'Cabaret', 66: 'New Wave', 67: 'Psychadelic', 68: 'Rave',
    69: 'Showtunes', 70: 'Trailer', 71: 'Lo-Fi', 72: 'Tribal',
    73: 'Acid Punk', 74: 'Acid Jazz', 75: 'Polka', 76: 'Retro',
    77: 'Musical', 78: 'Rock & Roll', 79: 'Hard Rock',
}

# --------------------------------------------------------------- duration

BITRATES_V1L3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320]
BITRATES_V1L2 = [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384]
BITRATES_V1L1 = [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448]
SR = {0: [44100, 48000, 32000], 1: [22050, 24000, 16000], 2: [11025, 12000, 8000]}


def mp3_duration(path):
    """Estimate seconds from the first MPEG frame + file size (CBR fallback)."""
    size = path.stat().st_size
    with open(path, 'rb') as fh:
        data = fh.read(min(size, 512 * 1024))
    # skip id3v2
    off = 0
    if data[:3] == b'ID3' and len(data) > 10:
        off = 10 + syncsafe(data[6:10])
    i, limit = off, len(data) - 4
    while i < limit:
        if data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0:
            b1, b2 = data[i + 1], data[i + 2]
            ver = (b1 >> 3) & 0x03      # 3 = v1, 2 = v2, 0 = v2.5
            layer = (b1 >> 1) & 0x03    # 1 = L3, 2 = L2, 3 = L1
            br_idx = (b2 >> 4) & 0x0F
            sr_idx = (b2 >> 2) & 0x03
            if ver == 3 and layer in (1, 2, 3) and 0 < br_idx < 15 and sr_idx < 3:
                table = {1: BITRATES_V1L3, 2: BITRATES_V1L2,
                         3: BITRATES_V1L1}[layer]
                kbps = table[br_idx]
                sr = SR[0][sr_idx]
                if kbps:
                    return size * 8.0 / (kbps * 1000)
        i += 1
    return 0.0


def ffprobe_duration(path):
    try:
        proc = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
            check=True, capture_output=True, text=True, timeout=60,
        )
        return float(proc.stdout.strip())
    except Exception:
        return None


def duration_str(seconds):
    seconds = max(0, int(round(seconds or 0)))
    if seconds >= 3600:
        return f'{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}'
    return f'{seconds // 60:02d}:{seconds % 60:02d}'


# --------------------------------------------------------------- helpers

def slugify(text, fallback='track'):
    cleaned = ID.sub('-', (text or '').strip()).strip('-').lower()
    cleaned = re.sub(r'-{2,}', '-', cleaned)
    return (cleaned or fallback)[:70]


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def split_artist(raw):
    """'Artist - Title' fallback parsing lives in main; here just clean."""
    return (raw or '').strip()


def year_int(raw):
    m = re.search(r'\d{4}', raw or '')
    return int(m.group()) if m else None


# --------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description='Rebuild SONORA audio manifest from files on disk.')
    ap.add_argument('--check', action='store_true',
                    help='report only, do not write; exit 1 if the manifest is stale')
    args = ap.parse_args()

    if not AUDIO_DIR.is_dir():
        print('audio/ directory not found.', file=sys.stderr)
        return 1

    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))
        if not isinstance(manifest, dict):
            manifest = {}
    except (OSError, ValueError):
        manifest = {}
    readme = manifest.get('_readme')
    old_tracks = manifest.get('tracks') if isinstance(manifest.get('tracks'), list) else []

    by_file = {t.get('file'): t for t in old_tracks if isinstance(t, dict) and t.get('file')}
    by_sha = {t.get('sha256'): t for t in old_tracks
              if isinstance(t, dict) and t.get('sha256')}
    taken_ids = {str(t.get('id', '')).lower() for t in old_tracks if isinstance(t, dict)}

    files = sorted(p for p in AUDIO_DIR.iterdir()
                   if p.is_file() and p.suffix.lower() in AUDIO_EXTS)
    if not files:
        print('No audio files found in audio/.')

    new_tracks, used_ids, added, updated = [], set(), 0, 0

    for path in files:
        rel = f'audio/{path.name}'
        prev = by_file.get(rel)
        sha = sha256_of(path)
        if prev is None:
            prev = by_sha.get(sha)
        tags = read_id3(path)
        title = tags['title']
        if not title:
            stem = path.stem
            if ' - ' in stem:  # "Artist - Title" filename convention
                fa, ft = stem.split(' - ', 1)
                title, artist = ft.strip(), fa.strip()
                tags['artist'] = tags['artist'] or artist
            title = stem.replace('_', ' ').strip()
        artist = split_artist(tags['artist']) or 'Unknown artist'
        album = (tags['album'] or '').strip()

        base_id = slugify(title, slugify(path.stem))
        track_id = str(prev.get('id')) if prev and prev.get('id') else base_id
        if track_id.lower() in used_ids:
            track_id = base_id
        n = 2
        while track_id.lower() in used_ids:
            track_id = f'{base_id}-{n}'
            n += 1
        used_ids.add(track_id.lower())

        # cover: keep existing extraction unless tags changed file
        cover_rel = str(prev.get('cover') or '') if prev else ''
        if tags['cover']:
            ext = '.png' if 'png' in tags['cover_mime'].lower() else '.jpg'
            want_rel = f'audio/covers/{track_id}{ext}'
            want = ROOT / want_rel
            if cover_rel != want_rel or not want.exists():
                COVERS_DIR.mkdir(parents=True, exist_ok=True)
                if not args.check:
                    want.write_bytes(tags['cover'])
                cover_rel = want_rel

        secs = ffprobe_duration(path)
        if secs is None:
            secs = mp3_duration(path)
        dur = duration_str(secs) if secs else (prev.get('duration') if prev else '00:00')

        track = {
            'id': track_id,
            'file': rel,
            'title': title[:120],
            'artist': artist[:80],
            'album': album[:80],
            'year': year_int(str(tags['year'])) or (prev.get('year') if prev else None),
            'genre': (tags['genre'] or (prev.get('genre') if prev else '')) or '',
            'duration': dur,
            'cover': cover_rel,
        }
        # preserve hand-maintained / pipeline fields
        if prev:
            for key in ('sha256', 'telegram_file_unique_id', 'source',
                        'imported_at', 'added_at'):
                if prev.get(key) and not track.get(key):
                    track[key] = prev[key]
        track.setdefault('sha256', sha)

        if prev is None:
            added += 1
            print(f'+ {rel}  →  "{track["title"]}" — {track["artist"]} ({dur})')
        elif prev != track:
            updated += 1
            print(f'~ {rel}  ({dur})')
        new_tracks.append(track)

    # entries whose file disappeared
    gone = [t.get('file') for t in old_tracks
            if isinstance(t, dict) and t.get('file')
            and not (ROOT / str(t.get('file'))).exists()]
    for g in gone:
        print(f'- dropped missing file: {g}')

    # orphan cover cleanup
    if COVERS_DIR.is_dir():
        keep = {Path(t['cover']).name for t in new_tracks if t.get('cover')}
        for p in COVERS_DIR.iterdir():
            if p.is_file() and p.name not in keep:
                print(f'- removed orphan cover {p.name}')
                if not args.check:
                    p.unlink()

    out = {'_readme': readme or [
        'SONORA music manifest — generated by add_music.py. Do not edit by hand.',
        'Add music: drop the file into /audio/, run `python .github/scripts/add_music.py`, commit.',
        'Fields: id, file, title, artist, album, year, genre, duration, cover, sha256.',
        'cover points to art extracted from the file\'s own ID3 tags.',
    ], 'tracks': new_tracks}

    if args.check:
        drift = bool(added or updated or gone)
        print(f'check: {len(new_tracks)} tracks, {added} new, {updated} changed, '
              f'{len(gone)} gone → {"drift" if drift else "up to date"}')
        return 1 if drift else 0

    MANIFEST_PATH.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Done: {len(new_tracks)} track(s), {added} added, {updated} updated, '
          f'{len(gone)} removed → audio/manifest.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
