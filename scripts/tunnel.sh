#!/usr/bin/env bash
# Keep an SSH tunnel to the GPU pod open for the whole job (reconnects if it drops).
# Needs POD_SSH_HOST, POD_SSH_PORT and the key in ~/.ssh/pod. Prints nothing secret.
set -u
while true; do
  ssh -i ~/.ssh/pod -p "$POD_SSH_PORT" -q -N \
    -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$HOME/.ssh/pod_known_hosts" \
    -o ExitOnForwardFailure=yes -o ServerAliveInterval=20 -o ServerAliveCountMax=6 -o ConnectTimeout=20 \
    -L 8000:127.0.0.1:8000 -L 8011:127.0.0.1:8011 -L 8012:127.0.0.1:8012 -L 9911:127.0.0.1:9911 \
    "root@$POD_SSH_HOST" >/dev/null 2>&1
  echo "$(date -u +%T) tunnel exited ($?), reconnecting in 5 s" >> "$HOME/tunnel.log"
  sleep 5
done
