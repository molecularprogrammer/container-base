#!/usr/bin/env bash
set -euo pipefail

# Safely resolve the script's absolute directory (handles spaces and special characters)
DIRECTORY=$(cd `dirname $0` && pwd)
TEST_DIRECTORY=${DIRECTORY}/test_project
sudo rm -rf ${TEST_DIRECTORY}
mkdir ${TEST_DIRECTORY}

/bin/bash -e ./build.sh

docker run --rm -it \
  --user "$(id -u):$(id -g)" \
  --volume "${TEST_DIRECTORY}:/workspace" \
  ghcr.io/molecularprogrammer/container-base:latest \
  task --taskfile /project_template/Taskfile.yaml install tag=latest
