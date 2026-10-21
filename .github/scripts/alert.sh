#!/usr/bin/env bash
# Open (or add to) one GitHub issue when the site has a problem, and close it once things are healthy again.
# The issue mentions the repo owner, so GitHub emails them and notifies the GitHub app.
#   alert.sh open "what went wrong"     alert.sh close "what recovered"
set -u
TITLE="Site alert: data not updating"
num=$(gh issue list --state open --search "\"$TITLE\" in:title" --json number -q '.[0].number' 2>/dev/null)
now=$(TZ=America/Chicago date '+%b %-d, %-I:%M %p %Z')
run="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-}/actions/runs/${GITHUB_RUN_ID:-}"
if [ "$1" = "open" ]; then
  body="$now: $2

Run: $run"
  if [ -n "$num" ]; then gh issue comment "$num" --body "$body"
  else gh issue create --title "$TITLE" --body "@${GITHUB_REPOSITORY_OWNER:-} $body

The site keeps its last good version until this is fixed. This issue closes itself when a refresh succeeds."; fi
elif [ "$1" = "close" ] && [ -n "$num" ]; then
  gh issue close "$num" --comment "$now: $2"
fi
exit 0
