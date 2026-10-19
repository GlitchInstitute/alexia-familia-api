#!/usr/bin/env bash
# Starts the demo from a built image and asks for every request the demo suggests, over a real
# socket. It shows that the image starts as a user without rights, that its health check works,
# and that every route answers from inside a read-only container with no capabilities.
#
#   docker build --tag alexia-familia-api:local .
#   scripts/smoke_docker.sh alexia-familia-api:local
set -euo pipefail

image="${1:-alexia-familia-api:local}"
name="alexia-smoke-$$"

cleanup() {
  docker rm --force "$name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

fail() {
  echo "smoke_docker: $1" >&2
  docker logs "$name" >&2 || true
  exit 1
}

docker run --detach --name "$name" \
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges:true \
  --publish 127.0.0.1::8000 \
  "$image" alexia-api demo --host 0.0.0.0 --port 8000 >/dev/null

address=$(docker port "$name" 8000/tcp | head -n 1)
[ -n "$address" ] || fail "the container published no port"

for _ in $(seq 1 60); do
  curl --silent --fail --output /dev/null "http://$address/healthz" && break
  sleep 1
done
curl --silent --fail --output /dev/null "http://$address/healthz" || fail "the server never answered"

health=""
for _ in $(seq 1 90); do
  health=$(docker inspect --format '{{.State.Health.Status}}' "$name")
  [ "$health" = "healthy" ] && break
  sleep 1
done
[ "$health" = "healthy" ] || fail "the container is $health and not healthy"

user=$(docker exec "$name" id -u)
[ "$user" = "10001" ] || fail "the server runs as user $user and not 10001"

banner=$(docker logs "$name" 2>&1)
key=$(printf '%s\n' "$banner" | sed -n 's/^    \(afk_[A-Za-z0-9_-]*\)$/\1/p' | head -n 1)
[ -n "$key" ] || fail "the banner shows no key"
paths=$(printf '%s\n' "$banner" | sed -n 's|^    curl -H "Authorization: Bearer [^"]*" "http://[^/]*\(/[^"]*\)".*$|\1|p')
[ -n "$paths" ] || fail "the banner suggests no request"

count=0
while IFS= read -r path; do
  status=$(curl --silent --output /dev/null --write-out '%{http_code}' \
    --header "Authorization: Bearer $key" "http://$address$path") || fail "GET $path did not answer"
  [ "$status" = "200" ] || fail "GET $path answered $status and not 200"
  count=$((count + 1))
done <<<"$paths"

status=$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --header "Authorization: Bearer $key" "http://$address/v1/accounts/nobody/children")
[ "$status" = "404" ] || fail "an unknown account answered $status and not 404"

status=$(curl --silent --output /dev/null --write-out '%{http_code}' "http://$address/v1/accounts")
[ "$status" = "401" ] || fail "a request without a key answered $status and not 401"

echo "smoke_docker ok requests=$count"
