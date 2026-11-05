#!/bin/bash
# Forward local 127.0.0.1:${DG_LOCAL_PORT:-18000} to the VM's vLLM (127.0.0.1:8000).
# Usage: infra/llm-vm/tunnel.sh [start|stop|status]
set -euo pipefail
cd "$(dirname "$0")"

GCLOUD="${GCLOUD:-$HOME/google-cloud-sdk/bin/gcloud}"
NAME="${DG_VM_NAME:-deliverable-guard-llm}"
ZONE="$(cat .zone)"
PORT="${DG_LOCAL_PORT:-18000}"
PIDFILE=.tunnel.pid

case "${1:-start}" in
  start)
    if [ -f $PIDFILE ] && kill -0 "$(cat $PIDFILE)" 2>/dev/null; then echo "tunnel already running"; exit 0; fi
    "$GCLOUD" compute ssh "$NAME" --zone "$ZONE" -- -N -o ExitOnForwardFailure=yes \
      -o ServerAliveInterval=30 -L "127.0.0.1:${PORT}:127.0.0.1:8000" &
    echo $! > $PIDFILE
    echo "tunnel up: http://127.0.0.1:${PORT}/v1" ;;
  stop)
    [ -f $PIDFILE ] && kill "$(cat $PIDFILE)" 2>/dev/null || true
    rm -f $PIDFILE ;;
  status)
    curl -s -H "Authorization: Bearer $(cat .api_key)" "http://127.0.0.1:${PORT}/v1/models" || echo "not reachable" ;;
esac
