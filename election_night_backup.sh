#!/bin/bash
# Election-night backup: GitHub's timer can run late. Push-triggered runs start right away, so this
# nudges the GitHub workflow every 10 minutes from this Mac by pushing an empty commit.
# Run on Nov 3 from about 6:50 p.m. Central:   ./election_night_backup.sh
# Stop with Ctrl-C.
set -u
cd "$(dirname "$0")"
while true; do
  git pull -q --rebase origin main || { echo "pull failed; retrying in 60s"; sleep 60; continue; }
  git commit -q --allow-empty -m "Election night refresh $(date '+%H:%M %Z')" && git push -q origin main \
    && echo "$(date '+%H:%M:%S') refresh triggered" || echo "$(date '+%H:%M:%S') push failed"
  sleep 600
done
