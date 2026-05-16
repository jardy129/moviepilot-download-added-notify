#!/bin/sh

# qBittorrent external program hook for MoviePilot.
# Configure MP_BASE_URL and MP_API_TOKEN below, or pass them as environment variables.

MP_BASE_URL="${MP_BASE_URL:-http://moviepilot:3001}"
MP_API_TOKEN="${MP_API_TOKEN:-replace_with_moviepilot_api_token}"
MP_DOWNLOADER_NAME="${MP_DOWNLOADER_NAME:-Qbittorrent}"

EVENT="${1:-added}"
NAME="${2:-}"
HASH="${3:-}"
SAVE_PATH="${4:-}"
CATEGORY="${5:-}"
TAGS="${6:-}"
SIZE="${7:-}"
STATE="${8:-}"

if [ -z "$MP_BASE_URL" ] || [ -z "$MP_API_TOKEN" ] || [ "$MP_API_TOKEN" = "replace_with_moviepilot_api_token" ]; then
  echo "MoviePilot base URL or API token is not configured" >&2
  exit 2
fi

curl -fsS -X POST "${MP_BASE_URL%/}/api/v1/plugin/DownloadAddedNotify/qbittorrent?apikey=${MP_API_TOKEN}" \
  --data-urlencode "event=${EVENT}" \
  --data-urlencode "downloader=${MP_DOWNLOADER_NAME}" \
  --data-urlencode "name=${NAME}" \
  --data-urlencode "hash=${HASH}" \
  --data-urlencode "save_path=${SAVE_PATH}" \
  --data-urlencode "category=${CATEGORY}" \
  --data-urlencode "tags=${TAGS}" \
  --data-urlencode "size=${SIZE}" \
  --data-urlencode "state=${STATE}"
