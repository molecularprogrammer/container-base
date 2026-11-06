#!/usr/bin/env bash
set -euo pipefail

# Get the absolute directory where this script lives
DIRECTORY=$(cd "$(dirname "$0")" && pwd)

# Export current user IDs for container permission mapping
export HOST_UID=$(id -u)

export HOST_GID=$(id -g)

export HOST_DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)

# Force HOST_PWD to be the script's directory
export HOST_PWD="${DIRECTORY}"

CACHE_ROOT="${XDG_CACHE_HOME:-${HOME}/.cache}"

# Parse flags
ACTION="run"
if [[ "${1:-}" == "--attach" || "${1:-}" == "-a" ]]; then
    ACTION="exec"
    shift # Remove the flag from arguments so it doesn't get passed to the container
fi

if [[ "${ACTION}" == "run" ]]; then
    docker compose \
        --file "${DIRECTORY}/compose.yaml" \
        --project-directory "${DIRECTORY}" \
        run --rm --service-ports container-base task "${@:-default}"
else
    docker compose \
        --file "${DIRECTORY}/compose.yaml" \
        --project-directory "${DIRECTORY}" \
        exec container-base "${@:-bash}"
fi
