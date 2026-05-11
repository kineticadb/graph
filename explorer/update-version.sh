#!/usr/bin/env bash
# Sync EXPLORER_VERSION in KineticaGraphExplorer.html with the latest git tag.
#
# Recognises tag formats:
#   release/v7.2.3-ga-13  →  7.2.3.13
#   v7.2.3.13             →  7.2.3.13
#   7.2.3.13              →  7.2.3.13
#
# Run from anywhere; works on the file next to this script. Idempotent.
# Exits non-zero (and leaves the file unchanged) if no usable tag is found.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
html="$here/KineticaGraphExplorer.html"

if [[ ! -f "$html" ]]; then
    echo "update-version: $html not found" >&2
    exit 1
fi

# Latest tag reachable from HEAD
tag="$(git -C "$here" describe --tags --abbrev=0 2>/dev/null || true)"
if [[ -z "$tag" ]]; then
    echo "update-version: no git tag found — leaving EXPLORER_VERSION unchanged" >&2
    exit 1
fi

# Normalise → dotted four-segment
version="$(echo "$tag" | sed -E 's|^release/||; s|^v||; s|-ga-|.|')"

if ! [[ "$version" =~ ^[0-9]+(\.[0-9]+){2,3}$ ]]; then
    echo "update-version: tag '$tag' did not parse to a version (got '$version')" >&2
    exit 1
fi

current="$(grep -oE 'EXPLORER_VERSION = "[^"]+"' "$html" | head -1 | sed -E 's/.*"([^"]+)"/\1/')"
if [[ "$current" == "$version" ]]; then
    echo "update-version: already at $version (tag $tag)"
    exit 0
fi

# In-place rewrite of the version constant + the tag in the trailing comment
sed -i -E \
    -e "s|(EXPLORER_VERSION = \")[^\"]+(\")|\1${version}\2|" \
    -e "s|(release/v[0-9]+\.[0-9]+\.[0-9]+-ga-[0-9]+)|${tag}|" \
    "$html"

echo "update-version: $current → $version (from tag $tag)"
