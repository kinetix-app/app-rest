#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

sonar_port="${SONAR_PORT:-9000}"
sonar_host_url="http://127.0.0.1:${sonar_port}"
scanner_image="sonarsource/sonar-scanner-cli:12.2.0.4256_8.1.0@sha256:a3f4215076706c95a17a68c19322ee916e40a3acd081a8c1a1e839e0194afa57"

if [[ -z "${SONAR_TOKEN:-}" ]]; then
  echo "SONAR_TOKEN is required. Log in to ${sonar_host_url}, create a token under My Account > Security and add SONAR_TOKEN to .env." >&2
  exit 1
fi

echo "Starting local SonarQube (profile: sonar)..."
docker compose --profile sonar up -d sonarqube

echo "Waiting for SonarQube to report UP at ${sonar_host_url} (this can take 1-2 minutes)..."
deadline=$((SECONDS + 300))
until curl -fsS "${sonar_host_url}/api/system/status" 2>/dev/null | grep -q '"status":"UP"'; do
  if ((SECONDS >= deadline)); then
    echo "SonarQube did not become ready within 300s. Check: docker compose logs sonarqube" >&2
    exit 1
  fi
  sleep 5
done

echo "Running tests with coverage..."
uv run --locked pytest -m 'not integration' --cov=. --cov-report=xml "$@"

echo "Running SonarScanner..."
docker run --rm \
  --add-host=host.docker.internal:host-gateway \
  -e SONAR_HOST_URL="http://host.docker.internal:${sonar_port}" \
  -e SONAR_TOKEN="${SONAR_TOKEN}" \
  -v "${repo_root}:/usr/src" \
  -w /usr/src \
  "${scanner_image}"

echo "Analysis complete: ${sonar_host_url}/dashboard?id=kinetix-backend"
