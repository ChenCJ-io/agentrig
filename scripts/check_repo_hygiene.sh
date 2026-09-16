#!/usr/bin/env bash
# Tracked files must not leak machine-local paths, credentials, or the private
# names of systems this repository is tested against.
#
# The check runs in two layers:
#
#   1. A baseline pattern kept in this file. It only matches structural leaks
#      (absolute home paths, private keys, obvious API tokens), so publishing
#      it costs nothing.
#   2. A private denylist of internal product, service and codename strings,
#      read from `.hygiene-denylist` (gitignored) or $HYGIENE_DENYLIST. The
#      list is deliberately NOT tracked: a denylist of internal names is itself
#      an index of internal names, and committing it republishes what it is
#      meant to keep out.
#
# Exclusions are limited to append-only or generated files. Documentation is
# never excluded — process documents are where private names actually leak.
set -euo pipefail

cd "$(dirname -- "$0")/.."

baseline='/Users/[a-z]|/home/[a-z]|BEGIN [A-Z ]*PRIVATE KEY|sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-'

pattern="$baseline"
source_label="baseline only"
if [[ -f .hygiene-denylist ]]; then
  private="$(grep -v -e '^[[:space:]]*#' -e '^[[:space:]]*$' .hygiene-denylist | paste -sd '|' -)"
  source_label=".hygiene-denylist"
elif [[ -n "${HYGIENE_DENYLIST:-}" ]]; then
  private="${HYGIENE_DENYLIST}"
  source_label="\$HYGIENE_DENYLIST"
else
  private=""
fi

if [[ -n "$private" ]]; then
  pattern="${pattern}|${private}"
elif [[ "${HYGIENE_STRICT:-0}" == "1" ]]; then
  echo "repository hygiene check failed: no private denylist available and HYGIENE_STRICT=1" >&2
  exit 1
else
  echo "note: no private denylist found; running the baseline pattern only" >&2
fi

if git -c core.quotepath=false ls-files -z -- . \
    ':!migrations/versions/**' \
    ':!scripts/check_repo_hygiene.sh' \
    ':!uv.lock' ':!web/package-lock.json' \
  | xargs -0 grep -n -I -i -E "$pattern"; then
  echo "repository hygiene check failed: forbidden terms above (${source_label})" >&2
  exit 1
fi
echo "repository hygiene check passed (${source_label})"
