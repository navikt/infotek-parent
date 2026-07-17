#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-$HOME/infotek}"
SOURCE_NPMRC="${ROOT}/platform/npm/.npmrc"

if [[ ! -f "${SOURCE_NPMRC}" ]]; then
  echo "Mangler kildefil: ${SOURCE_NPMRC}" >&2
  exit 1
fi

if [[ $# -eq 0 ]]; then
  echo "Bruk: $0 <repo> [repo...]" >&2
  exit 1
fi

for repo in "$@"; do
  target="${ROOT}/repos/${repo}/frontend/.npmrc"
  if [[ ! -f "${target}" ]]; then
    echo "Hopper over ${repo}: fant ikke ${target}" >&2
    continue
  fi

  cp "${SOURCE_NPMRC}" "${target}"
  echo "Synket .npmrc for ${repo}"
done
