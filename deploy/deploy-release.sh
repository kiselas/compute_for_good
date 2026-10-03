#!/usr/bin/env bash
# Installed as root-owned /opt/compute-for-good/bin/deploy-release.
set -Eeuo pipefail
umask 077
BASE=/opt/compute-for-good
sha=${1:-}
[[ $# == 1 && $sha =~ ^[0-9a-f]{40}$ ]] || { echo 'Exact 40-character release SHA required' >&2; exit 2; }
mkdir -p "$BASE/releases" "$BASE/backups"
exec 9>"$BASE/deploy.lock"
flock -w 600 9 || { echo 'Another deployment holds the lock' >&2; exit 1; }
[[ -f "$BASE/.env.production" ]] || { echo 'Private host environment is missing' >&2; exit 1; }
export DOCKER_CONFIG
DOCKER_CONFIG=$(mktemp -d "$BASE/.registry-XXXXXX")
trap 'rm -rf -- "$DOCKER_CONFIG"' EXIT

# Only an ephemeral GitHub job token is accepted. No permanent registry login.
actor=''
read -r -t 3 actor || true
if [[ -n "$actor" ]]; then
    [[ $actor =~ ^[A-Za-z0-9_-]+$ ]] || { echo 'Invalid registry account' >&2; exit 2; }
    read -r -t 3 registry_token
    [[ -n "$registry_token" ]] || { echo 'Registry token missing' >&2; exit 2; }
    printf '%s' "$registry_token" | docker login ghcr.io -u "$actor" --password-stdin
    unset registry_token
fi

if [[ ! -d "$BASE/source.git" ]]; then
    git init --bare "$BASE/source.git" >/dev/null
    git --git-dir="$BASE/source.git" remote add origin https://github.com/kiselas/compute_for_good.git
fi
git --git-dir="$BASE/source.git" fetch --depth=1 origin "$sha"
[[ $(git --git-dir="$BASE/source.git" rev-parse FETCH_HEAD) == "$sha" ]]
release="$BASE/releases/$sha"
if [[ ! -f "$release/.complete" ]]; then
    stage=$(mktemp -d "$BASE/releases/.stage-XXXXXX")
    git --git-dir="$BASE/source.git" archive "$sha" | tar -x -C "$stage"
    printf 'RELEASE_SHA=%s\n' "$sha" > "$stage/release.env"
    touch "$stage/.complete"
    [[ ! -e "$release" ]] || { echo 'Incomplete existing release; inspect manually' >&2; exit 1; }
    mv "$stage" "$release"
fi
compose() {
    docker compose -p compute-for-good --env-file "$BASE/.env.production" \
        --env-file "$release/release.env" -f "$release/deploy/compose.shared.yaml" "$@"
}
compose config --quiet
if [[ -n "$actor" ]]; then
    compose pull
else
    # Initial admin bootstrap may preload the two immutable images locally.
    docker image inspect "ghcr.io/kiselas/compute-for-good-backend:$sha" >/dev/null
    docker image inspect "ghcr.io/kiselas/compute-for-good-frontend:$sha" >/dev/null
    compose pull postgres redis cfg-gateway
fi

current=''
[[ ! -f "$BASE/current-sha" ]] || current=$(cat "$BASE/current-sha")
if [[ "$current" == "$sha" ]] && curl -fsS --max-time 10 http://127.0.0.1:5181/api/ready >/dev/null; then
    echo "Release $sha is already ready"
    exit 0
fi

pg=$(docker ps -q --filter label=com.docker.compose.project=compute-for-good --filter label=com.docker.compose.service=postgres)
if [[ -n "$pg" ]]; then
    [[ "$pg" != *$'\n'* ]] || { echo 'Ambiguous PostgreSQL container' >&2; exit 1; }
    backup="$BASE/backups/pre-$sha-$(date -u +%Y%m%dT%H%M%SZ).dump"
    docker exec "$pg" pg_dump -U cfg -d cfg -Fc > "$backup.tmp"
    docker exec -i "$pg" pg_restore -l < "$backup.tmp" >/dev/null
    mv "$backup.tmp" "$backup"
    echo 'Pre-release database backup saved and archive index validated'
fi

failed() {
    echo 'Release failed; current-sha has not been advanced. Database backup retained.' >&2
    echo 'Inspect the schema and restore a compatible image; migrations are never downgraded automatically.' >&2
}
trap 'failed; rm -rf -- "$DOCKER_CONFIG"' ERR
compose up -d --wait --wait-timeout 240
okay=0
for _ in $(seq 1 60); do
    if curl -fsS --max-time 5 http://127.0.0.1:5181/api/ready >/dev/null; then okay=1; break; fi
    sleep 2
done
[[ $okay == 1 ]] || { echo 'Database, Redis or worker readiness failed' >&2; exit 1; }

for url in https://cf.nextdish.tech/ https://next-metrica.com/; do
    curl -fsS --max-time 20 "$url" >/dev/null
done
if [[ -n "$current" && "$current" != "$sha" ]]; then printf '%s\n' "$current" > "$BASE/previous-sha"; fi
printf '%s\n' "$sha" > "$BASE/current-sha.tmp"
mv "$BASE/current-sha.tmp" "$BASE/current-sha"
echo "Release $sha deployed; API and both workers are ready; neighbour HTTPS checks passed"
