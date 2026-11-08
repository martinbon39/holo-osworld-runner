#!/usr/bin/env bash
# Keep an SSH tunnel open for the whole job (reconnects if it drops). Prints nothing secret.
# Env: TUNNEL_USER, TUNNEL_HOST, TUNNEL_PORT, TUNNEL_KEY (key file), TUNNEL_FORWARDS (local=remote ports, e.g. "8000 9911"),
#      TUNNEL_KNOWN_HOSTS (known_hosts file; if it does not exist the host key is accepted on first use).
set -u
fw=(); for p in $TUNNEL_FORWARDS; do fw+=(-L "$p:127.0.0.1:$p"); done
if [ -s "$TUNNEL_KNOWN_HOSTS" ]; then hk=(-o StrictHostKeyChecking=yes); else hk=(-o StrictHostKeyChecking=accept-new); fi
while true; do
  ssh -i "$TUNNEL_KEY" -p "$TUNNEL_PORT" -q -N -o BatchMode=yes "${hk[@]}" -o UserKnownHostsFile="$TUNNEL_KNOWN_HOSTS" \
    -o ExitOnForwardFailure=yes -o ServerAliveInterval=20 -o ServerAliveCountMax=6 -o ConnectTimeout=20 \
    "${fw[@]}" "$TUNNEL_USER@$TUNNEL_HOST" >/dev/null 2>&1
  echo "$(date -u +%T) tunnel exited ($?), reconnecting in 5 s" >> "$HOME/tunnel.log"
  sleep 5
done
