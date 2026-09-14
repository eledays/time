#!/bin/sh
set -eu

database_path=${1:?"usage: backup-sqlite.sh DATABASE BACKUP_DIRECTORY [RETENTION_DAYS]"}
backup_directory=${2:?"usage: backup-sqlite.sh DATABASE BACKUP_DIRECTORY [RETENTION_DAYS]"}
retention_days=${3:-30}

case "$database_path:$backup_directory" in
    *"'"*|*"
"*) echo "paths must not contain quotes or newlines" >&2; exit 2 ;;
esac
case "$backup_directory" in
    /*) ;;
    *) echo "backup directory must be an absolute path" >&2; exit 2 ;;
esac
if [ "$backup_directory" = "/" ] || [ ! -f "$database_path" ]; then
    echo "refusing unsafe backup paths" >&2
    exit 2
fi
case "$retention_days" in
    *[!0-9]*|'') echo "retention days must be a non-negative integer" >&2; exit 2 ;;
esac

umask 077
mkdir -p "$backup_directory"
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
temporary_path="$backup_directory/.time-$timestamp.sqlite3.tmp"
final_path="$backup_directory/time-$timestamp.sqlite3"
trap 'rm -f "$temporary_path"' EXIT HUP INT TERM

sqlite3 "$database_path" ".timeout 30000" ".backup '$temporary_path'"
if [ "$(sqlite3 "$temporary_path" "PRAGMA integrity_check;")" != "ok" ]; then
    echo "backup integrity check failed" >&2
    exit 1
fi
mv "$temporary_path" "$final_path"
gzip "$final_path"
find "$backup_directory" -type f -name 'time-*.sqlite3.gz' -mtime "+$retention_days" -delete
trap - EXIT HUP INT TERM
