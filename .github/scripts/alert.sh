#!/usr/bin/env bash
# Open (or add to) one GitHub issue when the site has a problem, and close it once things are healthy again.
# The issue mentions the repo owner, so GitHub emails them and notifies the GitHub app.
#   alert.sh open "what went wrong"     alert.sh close "what recovered"
set -u
TITLE="${ALERT_TITLE:-Site alert: data not updating}"
num=$(gh issue list --state open --limit 50 --json number,title -q ".[] | select(.title == \"$TITLE\") | .number" 2>/dev/null | head -1)
now=$(TZ=America/Chicago date '+%b %-d, %-I:%M %p %Z')
run="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-}/actions/runs/${GITHUB_RUN_ID:-}"
if [ "$1" = "open" ]; then
  body="$now: $2

Run: $run"
  if [ -n "$num" ]; then gh issue comment "$num" --body "$body"
  else gh issue create --title "$TITLE" --body "@${GITHUB_REPOSITORY_OWNER:-} $body

The site keeps its last good version until this is fixed. This issue closes itself when a refresh succeeds."; fi
elif [ "$1" = "close" ]; then
  for n in $(gh issue list --state open --limit 50 --json number,title -q ".[] | select(.title == \"$TITLE\") | .number" 2>/dev/null); do
    gh issue close "$n" --comment "$now: $2"
  done
fi
exit 0
