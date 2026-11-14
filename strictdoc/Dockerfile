FROM python:3.12-slim-bookworm

ARG STRICTDOC_VERSION=0.30.4

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        git \
        openssh-client \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir "strictdoc==${STRICTDOC_VERSION}"

WORKDIR /workspace
