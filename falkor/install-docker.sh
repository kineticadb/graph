#!/usr/bin/env bash
# Install Docker Engine + Compose plugin on Ubuntu 24.04 (official Docker apt repo).
set -euo pipefail

echo ">> Removing any conflicting old packages (safe if none present)..."
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
  sudo apt-get remove -y "$pkg" 2>/dev/null || true
done

echo ">> Installing prerequisites..."
sudo apt-get update
sudo apt-get install -y ca-certificates curl

echo ">> Adding Docker's official GPG key..."
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo ">> Adding the Docker apt repository..."
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update

echo ">> Installing Docker Engine, CLI, containerd, buildx and compose plugins..."
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo ">> Adding $USER to the docker group (so you can run docker without sudo)..."
sudo usermod -aG docker "$USER"

echo ">> Enabling and starting Docker..."
sudo systemctl enable --now docker

echo ""
echo ">> Docker installed. Version:"
sudo docker --version
sudo docker compose version
echo ""
echo ">> NOTE: Log out and back in (or run 'newgrp docker') for group membership to take effect."
