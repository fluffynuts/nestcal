#!/usr/bin/env bash
# Release notes for a commit that has no pull request: the subject of each commit since the
# previous release, newest first. Merge commits are left out, so a range of nothing else prints nothing.
#
#   commit-notes.sh <sha> <stable: true|false>
#
# A stable release is compared with the previous stable release, so it lists everything that is
# new to people on stable. A -beta is compared with the nearest earlier release of any kind, so
# it lists what is new in that build. Needs the full history and the tags (fetch-depth: 0).
set -euo pipefail

sha="$1"
stable="$2"

describe=(describe --tags --abbrev=0 --match 'v[0-9]*')
if [ "$stable" = true ]; then
  describe+=(--exclude '*-beta')
fi

# From the parent, so a re-run for a commit that already carries its release tag still finds the one before.
if previous="$(git "${describe[@]}" "${sha}^" 2>/dev/null)"; then
  range="${previous}..${sha}"
  heading="### Changes since ${previous}"
else
  range="${sha}"
  heading="### Changes"
fi

commits="$(git log --no-merges --max-count=100 --pretty='format:- %s (%h)' "$range")"
if [ -n "$commits" ]; then
  printf '%s\n\n%s\n' "$heading" "$commits"
fi
