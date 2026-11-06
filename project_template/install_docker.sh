#!/usr/bin/env bash

set -euo pipefail

# Check for root privileges
if [[ "$EUID" -ne 0 ]]; then
    echo "Please run this script with sudo."
    exit 1
fi

echo "Updating package lists..."
apt-get update

echo "Installing prerequisites..."
apt-get install -y ca-certificates curl

echo "Adding Docker's official GPG key..."
install -m 0755 -d /etc/apt/keyrings

curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc

chmod a+r /etc/apt/keyrings/docker.asc

echo "Adding Docker repository..."
ARCH=$(dpkg --print-architecture)
CODENAME=$(. /etc/os-release && echo "$VERSION_CODENAME")

cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${CODENAME}
Components: stable
Architectures: ${ARCH}
Signed-By: /etc/apt/keyrings/docker.asc
EOF

echo "Installing Docker..."
apt-get update

apt-get install -y \
    docker-ce \
    docker-ce-cli \
    containerd.io \
    docker-buildx-plugin \
    docker-compose-plugin

echo "Enabling Docker service..."
systemctl enable docker
systemctl start docker

echo "Verifying installation..."
docker --version
docker compose version

docker run --rm hello-world

# Allow the current user to run Docker without sudo
if [[ -n "${SUDO_USER:-}" ]]; then
    echo "Adding ${SUDO_USER} to the docker group..."
    usermod -aG docker "$SUDO_USER"
fi

echo "Docker installation completed successfully!"
echo "Log out and log back in for group permissions to take effect."