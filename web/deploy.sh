#!/bin/bash
# =============================================================
# deploy.sh — One-command deploy to Google Cloud Compute Engine
#
# Prerequisites:
#   1. Install gcloud CLI: https://cloud.google.com/sdk/docs/install
#   2. Run: gcloud auth login
#   3. Run: gcloud config set project YOUR_PROJECT_ID
#   4. Update the variables below with your project details
#
# First-time VM setup:
#   This script creates the VM if it doesn't exist yet.
#   After first deploy, SSH into the VM and copy your secrets:
#     gcloud compute scp .env credentials.json token.json $VM_NAME:/opt/assistant-agent/secrets/ --zone=$VM_ZONE
#
# Usage (run from project root):
#   chmod +x web/deploy.sh
#   ./web/deploy.sh
# =============================================================

set -e

# Ensure Homebrew binaries (gcloud, docker) are in PATH
export PATH="/opt/homebrew/bin:$PATH"

# ─── CONFIGURATION (update these with your GCP details) ───
PROJECT_ID="claude-code-building-agent"      # Your Google Cloud project ID
VM_NAME="math-class-vm"                # Name for the VM (kept from original GCE setup)
VM_ZONE="me-west1-a"                   # Zone (me-west1 = Tel Aviv)
IMAGE_NAME="assistant-agent-app"        # Docker image name
# ──────────────────────────────────────────────────────────

# cd to project root (one level up from web/) so Docker can access all files
cd "$(dirname "$0")/.."

echo "=== Building Docker image ==="
docker build --platform linux/amd64 -f web/Dockerfile -t $IMAGE_NAME .

echo "=== Saving image to archive ==="
docker save $IMAGE_NAME | gzip > /tmp/assistant-agent.tar.gz

echo "=== Checking if VM exists ==="
if ! gcloud compute instances describe $VM_NAME --zone=$VM_ZONE --project=$PROJECT_ID &>/dev/null; then
    echo "=== Creating VM (first-time setup) ==="
    gcloud compute instances create $VM_NAME \
        --zone=$VM_ZONE \
        --project=$PROJECT_ID \
        --machine-type=e2-micro \
        --image-family=cos-stable \
        --image-project=cos-cloud \
        --tags=http-server,https-server

    echo "=== Opening firewall for HTTP/HTTPS ==="
    gcloud compute firewall-rules create allow-web \
        --project=$PROJECT_ID \
        --allow=tcp:80,tcp:443,tcp:8080 \
        --target-tags=http-server,https-server 2>/dev/null || true

    echo ""
    echo "VM created! Before running deploy again, copy your secrets:"
    echo "  gcloud compute ssh $VM_NAME --zone=$VM_ZONE --command='sudo mkdir -p /opt/assistant-agent/secrets /opt/assistant-agent/data/memory'"
    echo "  gcloud compute scp .env credentials.json token.json $VM_NAME:/opt/assistant-agent/secrets/ --zone=$VM_ZONE"
    echo ""
    echo "Then run ./deploy.sh again."
    rm /tmp/assistant-agent.tar.gz
    exit 0
fi

echo "=== Uploading image to VM ==="
gcloud compute scp /tmp/assistant-agent.tar.gz $VM_NAME:/tmp/ --zone=$VM_ZONE --project=$PROJECT_ID

echo "=== Loading image and restarting container on VM ==="
gcloud compute ssh $VM_NAME --zone=$VM_ZONE --project=$PROJECT_ID --command="
    docker load < /tmp/assistant-agent.tar.gz
    # Stop old container name (math-class) if still running from before rename
    docker stop math-class 2>/dev/null || true
    docker rm math-class 2>/dev/null || true
    docker stop assistant-agent 2>/dev/null || true
    docker rm assistant-agent 2>/dev/null || true
    # Migrate secrets/data from old path if new path doesn't exist yet
    if [ -d \$HOME/math-class ] && [ ! -d \$HOME/assistant-agent ]; then
        mv \$HOME/math-class \$HOME/assistant-agent
    fi
    docker run -d \
        --name assistant-agent \
        --restart=unless-stopped \
        -p 8080:8080 \
        --env-file \$HOME/assistant-agent/secrets/.env \
        -v \$HOME/assistant-agent/data:/app/data \
        -v \$HOME/assistant-agent/secrets/credentials.json:/app/credentials.json:ro \
        -v \$HOME/assistant-agent/secrets/token.json:/app/token.json \
        $IMAGE_NAME
    rm /tmp/assistant-agent.tar.gz
"

rm /tmp/assistant-agent.tar.gz

echo ""
echo "=== Deployed! ==="
EXTERNAL_IP=$(gcloud compute instances describe $VM_NAME --zone=$VM_ZONE --project=$PROJECT_ID --format='get(networkInterfaces[0].accessConfigs[0].natIP)')
echo "App is running at: http://$EXTERNAL_IP:8080"
echo ""
echo "To set up HTTPS with a custom domain, SSH into the VM and configure Caddy."
