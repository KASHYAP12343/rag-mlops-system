#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# start.sh — Safe startup script for the RAG MLOps project
#
# Problem: docker-compose.yml declares the `minikube` network as external.
# Docker Compose will FAIL with:
#   "network minikube declared as external, but could not be found"
# ...if minikube is not running (its Docker network doesn't exist yet).
#
# This script ensures the minikube network exists before starting Compose.
# ─────────────────────────────────────────────────────────────────────────────

set -e

NETWORK_NAME="minikube"

echo "==> Checking for Docker network: ${NETWORK_NAME}"

if docker network inspect "${NETWORK_NAME}" > /dev/null 2>&1; then
    echo "    ✔ Network '${NETWORK_NAME}' already exists — skipping creation."
else
    echo "    ✘ Network '${NETWORK_NAME}' not found."
    echo ""
    echo "    Option 1 (recommended): Start minikube, which creates it automatically:"
    echo "      minikube start"
    echo ""
    echo "    Option 2: Create it manually (Jenkins won't reach K8s, but all other"
    echo "              services will work — useful for local dev without K8s):"
    echo "      docker network create minikube"
    echo ""

    read -rp "    Create the network manually now? [y/N] " choice
    case "$choice" in
        y|Y)
            docker network create "${NETWORK_NAME}"
            echo "    ✔ Created Docker network '${NETWORK_NAME}'."
            ;;
        *)
            echo ""
            echo "    Aborting. Please run 'minikube start' first, then re-run this script."
            exit 1
            ;;
    esac
fi

echo ""
echo "==> Starting all services with docker-compose..."
docker-compose up "$@"