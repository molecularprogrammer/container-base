#!/usr/bin/env bash
set -euo pipefail

DIRECTORY=$(cd "$(dirname "$0")" && pwd)
HOST_PROJECT_ROOT="${HOST_PWD:-${DIRECTORY}}"
IMAGE_TAG="integration-${GITHUB_SHA:-local}-$$"
IMAGE="local/container-base:${IMAGE_TAG}"
PROXY_IMAGE="local/ai-proxy:${IMAGE_TAG}"
STRICTDOC_IMAGE="local/strictdoc:${IMAGE_TAG}"
CONTAINER="container-base-integration-$$"
CONTAINER_TWO="container-base-integration-two-$$"
PROXY_CONTAINER="ai-proxy"
NETWORK="agent-mesh"
NETWORK_CREATED=0
PROXY_CREATED=0
HOST_TEST_PROJECT="${DIRECTORY}/test_project"
HOST_TEST_PROJECT_MOUNT="${HOST_PROJECT_ROOT}/test_project"
FETCH_DEPS_BACKUP="${HOST_TEST_PROJECT}/fetch_deps.yaml.integration-backup"
FETCH_DEPS_LOCK_BACKUP="${HOST_TEST_PROJECT}/fetch_deps.lock.integration-backup"
FETCH_DEPS_BACKUP_CREATED=0
FETCH_DEPS_LOCK_BACKUP_CREATED=0
DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)

if docker inspect "${PROXY_CONTAINER}" >/dev/null 2>&1; then
    echo "Refusing to run integration test: Docker container '${PROXY_CONTAINER}' already exists." >&2
    exit 1
fi

cleanup() {
    docker rm --force "${CONTAINER_TWO}" "${CONTAINER}" >/dev/null 2>&1 || true
    if [ "${PROXY_CREATED}" -eq 1 ]; then
        docker rm --force "${PROXY_CONTAINER}" >/dev/null 2>&1 || true
    fi
    if [ "${NETWORK_CREATED}" -eq 1 ]; then
        docker network rm "${NETWORK}" >/dev/null 2>&1 || true
    fi
    if [ "${FETCH_DEPS_BACKUP_CREATED}" -eq 1 ]; then
        mv "${FETCH_DEPS_BACKUP}" "${HOST_TEST_PROJECT}/fetch_deps.yaml"
    fi
    if [ "${FETCH_DEPS_LOCK_BACKUP_CREATED}" -eq 1 ]; then
        mv "${FETCH_DEPS_LOCK_BACKUP}" "${HOST_TEST_PROJECT}/fetch_deps.lock"
    fi
    docker image rm --force "${IMAGE}" "${PROXY_IMAGE}" "${STRICTDOC_IMAGE}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker build \
    --tag "${IMAGE}" \
    --file "${DIRECTORY}/Dockerfile" \
    "${DIRECTORY}"
docker build \
    --tag "${PROXY_IMAGE}" \
    --file "${DIRECTORY}/proxy/Dockerfile" \
    "${DIRECTORY}/proxy"
docker build \
    --tag "${STRICTDOC_IMAGE}" \
    --file "${DIRECTORY}/strictdoc/Dockerfile" \
    "${DIRECTORY}/strictdoc"

mkdir -p "${HOST_TEST_PROJECT}"
if [ -f "${HOST_TEST_PROJECT}/fetch_deps.yaml" ]; then
    mv "${HOST_TEST_PROJECT}/fetch_deps.yaml" "${FETCH_DEPS_BACKUP}"
    FETCH_DEPS_BACKUP_CREATED=1
fi
if [ -f "${HOST_TEST_PROJECT}/fetch_deps.lock" ]; then
    mv "${HOST_TEST_PROJECT}/fetch_deps.lock" "${FETCH_DEPS_LOCK_BACKUP}"
    FETCH_DEPS_LOCK_BACKUP_CREATED=1
fi
docker run --rm \
    --user "$(id -u):$(id -g)" \
    --volume "${HOST_TEST_PROJECT_MOUNT}:/workspace" \
    "${IMAGE}" task \
    --taskfile /project_template/Taskfile.yaml install "tag=${IMAGE_TAG}"
printf '{}\n' > "${HOST_TEST_PROJECT}/fetch_deps.yaml"

if ! docker network inspect "${NETWORK}" >/dev/null 2>&1; then
    docker network create "${NETWORK}" >/dev/null
    NETWORK_CREATED=1
fi

create_session() {
    local name=$1

    docker create \
        --name "${name}" \
        --user "$(id -u):$(id -g)" \
        --group-add "${DOCKER_GID}" \
        --network "${NETWORK}" \
        --volume "${HOST_TEST_PROJECT_MOUNT}:/workspace" \
        --volume /var/run/docker.sock:/var/run/docker.sock \
        --env HOST_UID="$(id -u)" \
        --env HOST_GID="$(id -g)" \
        --env HOST_DOCKER_GID="${DOCKER_GID}" \
        --env HOST_PWD="${HOST_TEST_PROJECT_MOUNT}" \
        --env SSH_AUTH_SOCK=/dev/null \
        "${IMAGE}" \
        sleep infinity >/dev/null
    docker start "${name}" >/dev/null
}

create_session "${CONTAINER}"
create_session "${CONTAINER_TWO}"

# Configure only a dummy upstream key; this test never sends model requests.
for session in "${CONTAINER}" "${CONTAINER_TWO}"; do
    docker exec --user "$(id -u):$(id -g)" "${session}" \
        sh -c 'printf "UPSTREAM_API_KEY=integration-test-key\n" > /workspace/.cline/.env'
done

docker exec \
    --user "$(id -u):$(id -g)" \
    --workdir /workspace \
    --env "PROXY_IMAGE=${PROXY_IMAGE}" \
    --env "HOST_PWD=${HOST_TEST_PROJECT_MOUNT}" \
    "${CONTAINER}" task cline:_proxy-ensure
PROXY_CREATED=1
PROXY_ID=$(docker inspect --format '{{.Id}}' "${PROXY_CONTAINER}")

docker exec \
    --user "$(id -u):$(id -g)" \
    --workdir /workspace \
    --env "PROXY_IMAGE=${PROXY_IMAGE}" \
    --env "HOST_PWD=${HOST_TEST_PROJECT_MOUNT}" \
    "${CONTAINER_TWO}" task cline:_proxy-ensure
test "$(docker inspect --format '{{.Id}}' "${PROXY_CONTAINER}")" = "${PROXY_ID}"

for session in "${CONTAINER}" "${CONTAINER_TWO}"; do
    docker exec --user "$(id -u):$(id -g)" "${session}" python3 -c \
        'import urllib.request; r = urllib.request.urlopen("http://ai-proxy:4000/health", timeout=2); assert r.status == 200 and r.read() == b"ok\n"'
done

docker exec --user "$(id -u):$(id -g)" --workdir /workspace "${CONTAINER}" \
    docker compose --project-directory /workspace config --quiet
grep -Fq "ghcr.io/molecularprogrammer/strictdoc:${IMAGE_TAG}" \
    "${HOST_TEST_PROJECT}/documentation/compose.yaml"
! grep -q '<tag>' "${HOST_TEST_PROJECT}/compose.yaml" \
    "${HOST_TEST_PROJECT}/documentation/compose.yaml"
docker exec \
    --user "$(id -u):$(id -g)" \
    --workdir /workspace \
    --env "STRICTDOC_IMAGE=${STRICTDOC_IMAGE}" \
    --env "HOST_PWD=${HOST_TEST_PROJECT_MOUNT}" \
    --env "HOST_UID=$(id -u)" \
    --env "HOST_GID=$(id -g)" \
    --env "HOST_DOCKER_GID=${DOCKER_GID}" \
    "${CONTAINER}" task documentation:build
test -s "${HOST_TEST_PROJECT}/documentation/output/html/index.html"

echo "Container, template, and shared-proxy integration tests passed."