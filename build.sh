#!/bin/bash -e

DIRECTORY=$(cd `dirname $0` && pwd)
IMAGE_TAG="sha-$(git -C "${DIRECTORY}" rev-parse HEAD)"

docker build \
  -t ghcr.io/molecularprogrammer/container-base:latest \
  -t "ghcr.io/molecularprogrammer/container-base:${IMAGE_TAG}" \
  -f "${DIRECTORY}/Dockerfile" \
  "${DIRECTORY}"

docker build \
  -t ghcr.io/molecularprogrammer/ai-proxy:latest \
  -t "ghcr.io/molecularprogrammer/ai-proxy:${IMAGE_TAG}" \
  -f "${DIRECTORY}/proxy/Dockerfile" \
  "${DIRECTORY}/proxy"

docker build \
  -t ghcr.io/molecularprogrammer/strictdoc:latest \
  -t "ghcr.io/molecularprogrammer/strictdoc:${IMAGE_TAG}" \
  -f "${DIRECTORY}/strictdoc/Dockerfile" \
  "${DIRECTORY}/strictdoc"
