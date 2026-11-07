FROM ubuntu:24.04

ARG TASK_VERSION=3.45.4
ARG PYTHON_VERSION=3.12
ARG NODE_VERSION=22

ENV DEBIAN_FRONTEND=noninteractive

# [Keep your existing apt-get install block unchanged]
RUN apt-get update && apt-get -y install --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        git \
        openssh-client \
        python${PYTHON_VERSION} \
        python${PYTHON_VERSION}-dev \
        python3-yaml \
        libnss3 \
        libnspr4 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libdbus-1-3 \
        libexpat1 \
        libfontconfig1 \
        libgbm1 \
        libglib2.0-0 \
        libgtk-3-0 \
        libpango-1.0-0 \
        libx11-6 \
        libx11-xcb1 \
        libxcb1 \
        libxcomposite1 \
        libxdamage1 \
        libxext6 \
        libxfixes3 \
        libxi6 \
        libxrandr2 \
        libxrender1 \
        libxtst6 \
        gstreamer1.0-plugins-base \
    && curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash - \
    && apt-get -y install --no-install-recommends nodejs \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get -y install --no-install-recommends docker-ce-cli docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

RUN ssh-keyscan -H github.com >> /etc/ssh/ssh_known_hosts

RUN git config --global --add safe.directory /workspace

RUN curl -fsSL "https://github.com/go-task/task/releases/download/v${TASK_VERSION}/task_linux_amd64.tar.gz" \
    | tar xz -C /usr/local/bin task

# Copy local proxy script into the image
COPY fetch_deps.py /opt/fetch_deps.py

# Copy project template
WORKDIR /project_template
COPY project_template .
COPY .cline/.env.example .cline/Taskfile.yaml .cline/
COPY .cline/rules/coding-standards.md .cline/rules/documentation.md .cline/rules/
COPY LICENSE ./LICENSE

WORKDIR /workspace

CMD ["task"]
