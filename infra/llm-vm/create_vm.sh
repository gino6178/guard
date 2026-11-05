#!/bin/bash
# Create the dedicated LLM VM (A100 40GB). Tries several zones until capacity is found.
# Usage: infra/llm-vm/create_vm.sh            (writes the API key to infra/llm-vm/.api_key)
set -euo pipefail
cd "$(dirname "$0")"

GCLOUD="${GCLOUD:-$HOME/google-cloud-sdk/bin/gcloud}"
NAME="${DG_VM_NAME:-deliverable-guard-llm}"
MODEL="${DG_MODEL:-Qwen/Qwen3-32B-AWQ}"
ZONES="${DG_ZONES:-us-central1-a us-central1-b us-central1-c us-central1-f us-east1-b us-west1-b us-west4-b asia-northeast1-a asia-northeast3-b europe-west4-a}"

[ -f .api_key ] || (head -c 24 /dev/urandom | base64 | tr -d '/+=' > .api_key && chmod 600 .api_key)
API_KEY="$(cat .api_key)"

for Z in $ZONES; do
  echo "== trying $Z"
  if "$GCLOUD" compute instances create "$NAME" \
      --zone "$Z" \
      --machine-type a2-highgpu-1g \
      --accelerator type=nvidia-tesla-a100,count=1 \
      --maintenance-policy TERMINATE \
      --image-family pytorch-2-9-cu129-ubuntu-2204-nvidia-580 \
      --image-project deeplearning-platform-release \
      --boot-disk-size 200GB --boot-disk-type pd-balanced \
      --labels owner=deliverable-guard,purpose=llm-api \
      --metadata "install-nvidia-driver=True,dg-model=${MODEL},dg-api-key=${API_KEY},dg-max-len=32768" \
      --metadata-from-file startup-script=startup.sh; then
    echo "$Z" > .zone
    echo "created $NAME in $Z"
    exit 0
  fi
done
echo "no zone had capacity" >&2
exit 1
