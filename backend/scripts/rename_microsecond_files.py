#!/usr/bin/env python3
"""
One-time migration script to rename files with .000000 microseconds in their filenames.
Removes the microsecond portion to match database timestamp format.
"""
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import EXTRACTED_AUDIO_DIR, SPECTROGRAM_DIR

def rename_files_in_directory(directory, dry_run=True):
    """Rename files with .000000 pattern in their names."""
    renamed_count = 0
    pattern = '.000000.'

    for filename in os.listdir(directory):
        if pattern in filename:
            old_path = os.path.join(directory, filename)
            new_filename = filename.replace('.000000.', '.')
            new_path = os.path.join(directory, new_filename)

            if dry_run:
                print(f"[DRY RUN] Would rename: {filename} -> {new_filename}")
            else:
                os.rename(old_path, new_path)
                print(f"Renamed: {filename} -> {new_filename}")

            renamed_count += 1

    return renamed_count

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Rename files with microseconds in filenames')
    parser.add_argument('--execute', action='store_true', help='Actually rename files (default is dry-run)')
    args = parser.parse_args()

    dry_run = not args.execute

    if dry_run:
        print("DRY RUN MODE - No files will be modified")
        print("Run with --execute to apply changes\n")
    else:
        print("EXECUTING - Files will be renamed\n")

    # Rename audio files
    print(f"Scanning audio directory: {EXTRACTED_AUDIO_DIR}")
    audio_count = rename_files_in_directory(EXTRACTED_AUDIO_DIR, dry_run)
    print(f"Audio files {'would be' if dry_run else ''} renamed: {audio_count}\n")

    # Rename spectrogram files
    print(f"Scanning spectrogram directory: {SPECTROGRAM_DIR}")
    spec_count = rename_files_in_directory(SPECTROGRAM_DIR, dry_run)
    print(f"Spectrogram files {'would be' if dry_run else ''} renamed: {spec_count}\n")

    total = audio_count + spec_count
    print(f"Total files {'would be' if dry_run else ''} renamed: {total}")
