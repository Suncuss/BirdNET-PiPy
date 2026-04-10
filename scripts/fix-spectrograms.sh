#!/bin/bash
# Fix spectrograms affected by the bbox_inches='tight' regression (Mar 14-27 2026).
# Runs inside the API container which has all required dependencies.
#
# Usage:
#   ./scripts/fix-spectrograms.sh [--dry-run] [--workers N]
#
# Options:
#   --dry-run      Only scan and report affected files, don't regenerate
#   --workers N    Number of parallel workers (default: 2)

set -e

# Find the API container
API_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E 'birdnet.*api' | head -1)

if [ -z "$API_CONTAINER" ]; then
    echo "Error: BirdNET API container is not running."
    echo "Start the service first: systemctl start birdnet"
    exit 1
fi

echo "Using container: $API_CONTAINER"

docker exec -t "$API_CONTAINER" python -u -c "
import sys
sys.argv = ['fix-spectrograms'] + '''$@'''.split()

import argparse
import os
import tempfile
import subprocess
import time
import multiprocessing

from PIL import Image

from config.settings import EXTRACTED_AUDIO_DIR, SPECTROGRAM_DIR
from core.migration_audio import _build_spectrogram_title_from_audio_filename
from core.utils import generate_spectrogram

BUGGY_WIDTH = 1250
# Bug was introduced Mar 14 2026 — anything older is guaranteed correct
BUG_START_MTIME = 1773446400  # 2026-03-14T00:00:00Z
BAR_WIDTH = 40

def progress_bar(current, total, regenerated, skipped, errors, elapsed):
    pct = current / total if total else 0
    filled = int(BAR_WIDTH * pct)
    bar = '#' * filled + '-' * (BAR_WIDTH - filled)

    if current > 0 and pct < 1:
        eta = elapsed / current * (total - current)
        if eta >= 3600:
            eta_str = f'{int(eta // 3600)}h{int((eta % 3600) // 60)}m'
        elif eta >= 60:
            eta_str = f'{int(eta // 60)}m{int(eta % 60)}s'
        else:
            eta_str = f'{int(eta)}s'
    else:
        eta_str = '--'

    line = f'\r[{bar}] {current}/{total} ({pct:.0%})  fixed:{regenerated} skip:{skipped} err:{errors}  ETA:{eta_str}  '
    sys.stdout.write(line)
    sys.stdout.flush()


def regenerate_one(spec_filename):
    \"\"\"Regenerate a single spectrogram. Returns ('ok'|'skip'|'error').\"\"\"
    base_name = os.path.splitext(spec_filename)[0]
    spectrogram_path = os.path.join(SPECTROGRAM_DIR, spec_filename)
    temp_wav = None

    try:
        audio_path = None
        for ext in ('.mp3', '.wav'):
            candidate = os.path.join(EXTRACTED_AUDIO_DIR, f'{base_name}{ext}')
            if os.path.exists(candidate):
                audio_path = candidate
                break

        if not audio_path:
            return 'skip'

        if audio_path.lower().endswith('.wav'):
            wav_path = audio_path
        else:
            temp_fd, temp_wav = tempfile.mkstemp(suffix='.wav')
            os.close(temp_fd)
            subprocess.run([
                'ffmpeg', '-y', '-loglevel', 'error',
                '-i', audio_path,
                '-ar', '48000', '-ac', '1',
                temp_wav
            ], check=True, timeout=60)
            wav_path = temp_wav

        title = _build_spectrogram_title_from_audio_filename(os.path.basename(audio_path))
        generate_spectrogram(wav_path, spectrogram_path, title)
        return 'ok'

    except Exception:
        return 'error'

    finally:
        if temp_wav and os.path.exists(temp_wav):
            try:
                os.unlink(temp_wav)
            except Exception:
                pass


parser = argparse.ArgumentParser()
parser.add_argument('--dry-run', action='store_true')
parser.add_argument('--workers', type=int, default=2)
args = parser.parse_args()

# Scan
print('Scanning spectrograms for buggy dimensions (width=1250)...')
affected = []
total = 0
scan_start = time.time()

entries = os.listdir(SPECTROGRAM_DIR)
checked = 0
skipped_old = 0
for i, f in enumerate(entries, 1):
    if not f.endswith('.webp'):
        continue
    total += 1
    path = os.path.join(SPECTROGRAM_DIR, f)
    try:
        if os.path.getmtime(path) < BUG_START_MTIME:
            skipped_old += 1
            continue
        checked += 1
        img = Image.open(path)
        if img.width == BUGGY_WIDTH:
            affected.append(f)
        img.close()
    except Exception:
        pass
    if i % 5000 == 0:
        sys.stdout.write(f'\r  Scanned {total} spectrograms ({skipped_old} pre-bug, {checked} checked, {len(affected)} affected)...')
        sys.stdout.flush()

scan_time = time.time() - scan_start
sys.stdout.write(f'\r  Scanned {total} spectrograms in {scan_time:.1f}s ({skipped_old} pre-bug skipped, {checked} checked)\n')
print(f'  Found {len(affected)} affected')

if not affected:
    print('Nothing to fix!')
    sys.exit(0)

if args.dry_run:
    print('Dry run -- no changes made.')
    sys.exit(0)

workers = args.workers
print()
print(f'Regenerating {len(affected)} spectrograms with {workers} workers...')
print()

regenerated = 0
skipped = 0
errors = 0
start = time.time()
processed = 0

with multiprocessing.Pool(workers) as pool:
    for result in pool.imap_unordered(regenerate_one, affected, chunksize=10):
        processed += 1
        if result == 'ok':
            regenerated += 1
        elif result == 'skip':
            skipped += 1
        else:
            errors += 1

        if processed % 20 == 0 or processed == len(affected):
            elapsed = time.time() - start
            progress_bar(processed, len(affected), regenerated, skipped, errors, elapsed)

elapsed = time.time() - start
print()
print()
print(f'Done in {elapsed:.0f}s: {regenerated} regenerated, {skipped} skipped (no audio), {errors} errors')
"
