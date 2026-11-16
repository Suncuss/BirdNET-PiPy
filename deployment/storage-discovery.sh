#!/bin/bash
# Read host device and container mount metadata only. No mounting or disk writes.
set -eu

if [ "$#" -ne 1 ]; then
    echo 'Usage: storage-discovery.sh OUTPUT_JSON' >&2
    exit 2
fi
if ! command -v lsblk >/dev/null 2>&1; then
    echo 'Drive discovery unavailable: lsblk is not installed.' >&2
    exit 1
fi

snapshot="$1"
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -t 1 ]; then
    echo 'Reading connected-drive and protected-storage metadata (read-only)...'
fi

# Only mount paths are inspected; container environment/secrets are not read.
mounts=''
if container=$(cd "$project_root" && timeout 10 docker compose ps --quiet api); then
    if [ -n "$container" ]; then
        mounts=$(timeout 10 docker inspect --format '{{range .Mounts}}{{printf "%s\t%s\n" .Destination .Source}}{{end}}' "$container") || mounts=''
    fi
fi

filesystem_for_path() {
    local path
    if ! path=$(realpath -m -- "$1"); then
        printf 'null'
        return
    fi
    # The DB/settings file may not exist during first startup. The nearest
    # existing parent still identifies the filesystem that will contain it.
    while [ ! -e "$path" ] && [ "$path" != / ]; do
        path=$(dirname "$path")
    done
    timeout 10 findmnt --json --target "$path" --output MAJ:MIN || printf 'null'
}

filesystem_for_container_path() {
    local path="$1" destination source selected_destination='' selected_source=''
    while IFS=$'\t' read -r destination source; do
        [ -n "$destination" ] || continue
        if [[ "$path" == "$destination" || "$path" == "$destination/"* ]]; then
            if [ "${#destination}" -gt "${#selected_destination}" ]; then
                selected_destination="$destination"
                selected_source="$source"
            fi
        fi
    done <<< "$mounts"
    if [ -z "$selected_source" ]; then
        printf 'null'
    else
        filesystem_for_path "$selected_source${path#"$selected_destination"}"
    fi
}

mkdir -p "$(dirname "$snapshot")"
temporary=$(mktemp "${snapshot}.XXXXXX")
trap 'rm -f "$temporary"' EXIT
{
    printf '{"inventory":'
    timeout 10 lsblk --json --bytes --output NAME,PATH,TYPE,SIZE,MODEL,TRAN,ROTA,RO,FSTYPE,LABEL,MOUNTPOINTS,MAJ:MIN,SERIAL,WWN
    printf ',"protected":{"application":['
    separator=''
    while IFS=$'\t' read -r destination source; do
        [ -n "$destination" ] || continue
        # All application bind mounts, excluding data/media submounts.
        if [[ "$destination" == /app || ( "$destination" == /app/* && "$destination" != /app/data && "$destination" != /app/data/* ) ]]; then
            printf '%s' "$separator"
            filesystem_for_path "$source"
            separator=','
        fi
    done <<< "$mounts"
    printf '],"database":['
    filesystem_for_container_path /app/data/db/birds.db
    printf '],"settings":['
    filesystem_for_container_path /app/data/config/user_settings.json
    printf ']}}\n'
} > "$temporary"
chmod 644 "$temporary"
mv -f "$temporary" "$snapshot"
if [ -t 1 ]; then
    echo 'Drive information refreshed.'
fi
