#!/usr/bin/env bash
# Request a deployed API and fail unless it answers like a working one.
#
#     .github/scripts/smoke_test.sh https://fpl-api-six.vercel.app
#
# CI's tests run the app from requirements.txt in GitHub Actions, so they can't see
# a Vercel build that ships broken (FPL-86). This checks the deployment itself.
set -uo pipefail

base="${1:?usage: smoke_test.sh <deployment url>}"
case "$base" in
  http*) ;;
  *) base="https://$base" ;;  # Vercel's payload may send the host without a scheme
esac
base="${base%/}"
body=$(mktemp)
trap 'rm -f "$body"' EXIT

# Retries cover a cold start and a deployment whose alias is still settling.
fetch() {
  curl --silent --show-error --location --retry 3 --retry-delay 5 --retry-all-errors \
    --max-time 20 --output "$body" --write-out '%{http_code}' "$base$1"
}

failed=0
check() {
  local path=$1 filter=$2 status
  status=$(fetch "$path")
  if [ "$status" = 200 ] && jq -e "$filter" "$body" > /dev/null 2>&1; then
    echo "ok    $path"
  else
    echo "FAIL  $path: HTTP $status, expected 200 and $filter"
    head -c 500 "$body" 2>/dev/null
    echo
    failed=1
  fi
}

check /healthcheck '.status == "ok" and .database == "ok"'
# Goes through a real router and the database, as most requests do.
check /api/events 'type == "array" and length > 0'

exit $failed
