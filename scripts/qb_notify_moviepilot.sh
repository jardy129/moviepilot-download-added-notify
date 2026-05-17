#!/bin/sh

# qBittorrent external program hook for MoviePilot.
# Configure MP_BASE_URL and MP_NOTIFY_TOKEN below, or pass them as environment variables.

MP_BASE_URL="${MP_BASE_URL:-http://moviepilot:3001}"
MP_NOTIFY_TOKEN="${MP_NOTIFY_TOKEN:-replace_with_plugin_notify_token}"
MP_DOWNLOADER_NAME="${MP_DOWNLOADER_NAME:-Qbittorrent}"

EVENT="${1:-added}"
NAME="${2:-}"
HASH="${3:-}"
SAVE_PATH="${4:-}"
CATEGORY="${5:-}"
TAGS="${6:-}"
SIZE="${7:-}"
TRACKER="${8:-}"
CONTENT_PATH="${9:-}"

if [ -z "$MP_BASE_URL" ] || [ -z "$MP_NOTIFY_TOKEN" ] || [ "$MP_NOTIFY_TOKEN" = "replace_with_plugin_notify_token" ]; then
  echo "MoviePilot base URL or plugin notify token is not configured" >&2
  exit 2
fi

curl -fsS -X POST "${MP_BASE_URL%/}/api/v1/plugin/DownloadAddedNotify/qbittorrent?token=${MP_NOTIFY_TOKEN}" \
  --data-urlencode "event=${EVENT}" \
  --data-urlencode "downloader=${MP_DOWNLOADER_NAME}" \
  --data-urlencode "name=${NAME}" \
  --data-urlencode "hash=${HASH}" \
  --data-urlencode "save_path=${SAVE_PATH}" \
  --data-urlencode "category=${CATEGORY}" \
  --data-urlencode "tags=${TAGS}" \
  --data-urlencode "size=${SIZE}" \
  --data-urlencode "tracker=${TRACKER}" \
  --data-urlencode "content_path=${CONTENT_PATH}"
