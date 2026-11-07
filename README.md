# Base Container

This contains a baseline development container and project template for the molecularprogrammer
organization projects.

It attempts to be a local-first solution with no lock-in to any particular cloud services. It
accomplishes this by using the repository as the single source of truth.

## Dependencies

The development environment is containerized, and requires Docker Compose to use.

Refer to [the official documentation](https://docs.docker.com/get-started/) for installation
instructions.

The official installation and setup documentation is rather fragmented, so you can optionally use
the following convenience scripts:

- On Ubuntu-based Linux distros, run `sudo ./install_docker.sh`
- On MS Windows, run `installer_docker.bat`

## Install Project Template

Choose `IMAGE_TAG` as `sha-` followed by the full commit SHA shown for a
successful run of the `Publish Docker image` workflow. That workflow publishes
all three images under the same commit tag. Then run this in a git repo to copy in
the project template:

``` bash
IMAGE_TAG=sha-REPLACE_WITH_FULL_COMMIT_SHA
docker run --rm -it --user "$(id -u):$(id -g)" -v "$PWD:/workspace" \
  "ghcr.io/molecularprogrammer/container-base:${IMAGE_TAG}" task \
  --taskfile /project_template/Taskfile.yaml install "tag=${IMAGE_TAG}"
```

Replace `REPLACE_WITH_FULL_COMMIT_SHA` with the workflow run's actual commit SHA
before running the command.

You should now be able to run `./task.sh` for a full list of tasks available.
See [README](project_template/README.md) for more details on what this is and how to use it.

See the installed README.md that appears in the project root after installation, or look at the
original copy of this file in [project_template/README.md](project_template/README.md).

## Build

Run `./build.sh` to build the developer, proxy, and StrictDoc images locally.

## Test

Run `task test` for the proxy unit tests and the container integration test. The integration test
builds the images, installs the template in two disposable developer containers, checks pinned image
tags and Compose configuration, then has the first Cline session start the shared proxy and the
second detect and reuse it. It uses a dummy upstream key and only calls `/health`; no real provider
key or model request is needed. Documentation export uses the standalone StrictDoc image and a
host-mounted temporary project with an empty dependency manifest, so it needs no SSH credentials or
external Git repositories. `install_test.sh` and `serve_test.sh` remain available for manual setup
and live-server checks.

## Publish

Merge changes to the `main` branch. The CI pipeline handles publishing to the container registry.
