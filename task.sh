#!/usr/bin/env bash
set -euo pipefail

# Get the absolute directory where this script lives
DIRECTORY=$(cd "$(dirname "$0")" && pwd)

# Export current user IDs for container permission mapping
export HOST_UID
HOST_UID=$(id -u)

export HOST_GID
HOST_GID=$(id -g)

# Export the host Docker socket's group ID for Docker-out-of-Docker access.
export HOST_DOCKER_GID="${HOST_DOCKER_GID:-}"
if [[ -z "${HOST_DOCKER_GID}" ]]; then
    if command -v stat >/dev/null 2>&1 && [[ -S /var/run/docker.sock ]]; then
        if [[ "$(uname)" == "Darwin" ]]; then
            HOST_DOCKER_GID=$(stat -f '%g' /var/run/docker.sock 2>/dev/null || true)
        else
            HOST_DOCKER_GID=$(stat -c '%g' /var/run/docker.sock 2>/dev/null || true)
        fi
    fi

    if [[ ! "${HOST_DOCKER_GID}" =~ ^[0-9]+$ ]] && command -v getent >/dev/null 2>&1; then
        HOST_DOCKER_GID=$(getent group docker 2>/dev/null | cut -d: -f3 || true)
    fi

    if [[ ! "${HOST_DOCKER_GID}" =~ ^[0-9]+$ ]]; then
        echo "Unable to determine the Docker socket group ID." >&2
        echo "Set HOST_DOCKER_GID explicitly, or ensure /var/run/docker.sock exists and is accessible." >&2
        exit 1
    fi
fi

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
