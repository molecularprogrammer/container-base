# Project Template

[TOC]

## Overview

Project description.

---

## Dependencies

The development environment is containerized, and requires Docker Compose to use.

Refer to [the official documentation](https://docs.docker.com/get-started/) for installation
instructions.

The official installation and setup documentation is rather fragmented, so you can optionally use
the following convenience scripts:

- On Ubuntu-based Linux distros, run `sudo ./install_docker.sh`
- On MS Windows, run `installer_docker.bat`

## Run Tasks

Run `./task.sh` to see the available project tasks. Tasks run in the base development container.

### Shared Cline proxy setup

The Cline proxy is optional. To use the shared proxy, copy `.cline/.env.example` to
`.cline/.env`, set a real `UPSTREAM_API_KEY`, and optionally adjust `UPSTREAM_URL`,
`UPSTREAM_AUTH_HEADER`, and `UPSTREAM_AUTH_SCHEME`. Running `./task.sh cline:launch` starts the
shared proxy on demand and attaches the developer container to `agent-mesh`; the real key is passed
only to the proxy. The singleton uses one provider account and key shared by all projects; the first
project that starts it supplies those settings. Configure Cline's OpenAI-compatible provider
manually with base URL `http://ai-proxy:4000` and a dummy API key.
Do not commit `.cline/.env`.

The shared proxy is a singleton with one upstream configuration. All projects using it must use the
same provider account and key. The first project that starts it supplies that configuration; changing
it requires recreating the `ai-proxy` container.

Without `.cline/.env`, the Cline tasks leave your provider settings untouched and launch Cline
normally, allowing you to use Cline's own provider setup. Non-Cline tasks do not need proxy
credentials or a Cline environment file.

Each Cline worktree gets an isolated `.cline` config/data directory. Its provider/model settings are
stored in `.cline/data/settings/providers.json`, and its session history is stored under
`.cline/data`. Existing worktree provider settings are preserved; otherwise they are initialized
from the project settings. The proxy is reachable at `ai-proxy:4000` only from containers attached
to `agent-mesh`.

The proxy forwards request paths beneath `UPSTREAM_URL` (use the provider origin, such as
`https://api.openai.com`). Optional `MODEL_MAP` JSON translates model names and `ROUTE_MAP` JSON
maps incoming path prefixes to upstream path prefixes.
Upstream rate-limit telemetry is available at `GET /rate-limits`; 429 `Retry-After` headers cause
a bounded cooldown shared by requests handled by this proxy process, not across proxy replicas.

---

## Documentation

Documentation is intended to enable self-onboarding. Tribal knowledge should not be required.

### Project Documentation

Documentation that is published as a website and maintained as Git-tracked source is located in the
[documentation folder](documentation).

To support requirements traceability and give developers and coding agents an authoritative
description of expected behavior, this project uses a spec-driven development system. Git-tracked
documentation is the source of truth. GitHub Issues are for reporting problems and feedback; accepted
plans and behavior changes belong in reviewed documentation and code changes linked back to those
issues.

See the following articles for more information on spec-driven development:

- [IBM article](https://www.ibm.com/think/topics/spec-driven-development)
- [Microsoft article](https://developer.microsoft.com/blog/spec-driven-development-ai-native-engineering/)

### Developer-Only Documentation

The contents of this repo are documented in a heirarchy of repository architecture files
(*.arch.md) that live alongside the files they are most closely related to. This meta data can help
other developers (as well as language models) quickly understand the high-level intent and usage of
all folders and files.

The project architecture documentation in the [documentation folder](documentation) describes the
system from a requirements and externally observable perspective. This documentation describes how
those requirements are realized by the implementation in this repository. The two therefore
complement rather than duplicate one another.

Since IDEs like VSCode allow previewing rendered markdown, there is no need to "build"
this developer-only code architecture documentation, but it can optionally link back to the project
documentation for traceability, similar to code.

Start with the [root repo architecture document](.arch.md).

---

## Git Workflows

### Branches

Typically use one branch per work item.

### Merges

Changes get merged directly to the ‘main’ branch, which is used for production deployment.

Merges to ‘main’ are only possible through Pull Requests, which enforces reviews/approvals, and
shows pull request branch pipeline success status that encapsulates all automated checks. (A more
complex branching strategy can be introduced at any time, as the need arises.)

Prefer semi-linear merge to keep a clean Git history, while ensuring file change history is not
obfuscated by a move and squash.

### Pull Requests

Code reviews should generally be self-explanatory, with only a link to the issue tracker, and
whatever information is in the PR branch. If they are not self-explanatory, consider
updating the project documentation.
