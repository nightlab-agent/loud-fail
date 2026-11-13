#!/bin/sh
# Re-run the five integration trials behind CHECKS.md and write one log per tool here.
# Needs the five tools checked out side by side under LF_REPOS, and one input each
# tool accepts. Temporary paths in the logs are replaced with $TMPDIR.
set -u
: "${LF_REPOS:?parent folder of the tool checkouts}"
: "${LF_NOTE:?a still-true note}"
: "${LF_VIDEO:?a video short-preflight passes}"
: "${LF_API:?a claude-code.d.ts mod-api-index can index}"
: "${LF_PLUGIN_ROOT:?a plugin root folder plugin-lag accepts}"
: "${LF_PACKAGE:?a package folder npm-release-check passes}"
here=$(cd "$(dirname "$0")" && pwd)
lf="$here/../../loud_fail.py"
tmp=${TMPDIR:-/tmp}
out=$(mktemp -d "$tmp/lf-trial-out.XXXXXX")
cd "$out" || exit 2

trial() {
    name=$1; shift
    python3 "$lf" --timeout 30 "$@" > "$here/$name.txt" 2>&1
    rc=$?
    echo "exit $rc" >> "$here/$name.txt"
    awk -v t="$tmp" '{ gsub(t, "$TMPDIR"); for (n = length(t) - 1; n >= 8; n--) { p = substr(t, 1, n); if (substr($0, length($0) - n + 1) == p) { $0 = substr($0, 1, length($0) - n) "$TMPDIR"; break } } print }' "$here/$name.txt" > "$out/clean" && mv "$out/clean" "$here/$name.txt"
    printf '%s exit=%s\n' "$name" "$rc"
}

trial plugin-lag --valid-dir "$LF_PLUGIN_ROOT" \
    --expect missing-file=reject --expect empty-file=reject --expect non-utf8-file=reject \
    --expect unknown-flag=reject --expect path-with-spaces=accept -- \
    node "$LF_REPOS/plugin-lag/bin/plugin-lag.js" --root '{}'

trial still-true --valid "$LF_NOTE" \
    --expect missing-file=reject --expect directory-as-file=reject \
    --expect unknown-flag=reject --expect path-with-spaces=accept -- \
    node "$LF_REPOS/still-true/bin/still-true.js" '{}'

trial short-preflight --valid "$LF_VIDEO" \
    --expect missing-file=reject --expect empty-file=reject \
    --expect directory-as-file=reject --expect non-utf8-file=reject \
    --expect unknown-flag=reject --expect path-with-spaces=accept -- \
    node "$LF_REPOS/short-preflight/bin/short-preflight.js" '{}'

trial npm-release-check --valid-dir "$LF_PACKAGE" \
    --expect missing-file=reject --expect empty-file=reject \
    --expect directory-as-file=reject --expect non-utf8-file=reject \
    --expect unknown-flag=reject --expect path-with-spaces=accept -- \
    node "$LF_REPOS/npm-release-check/bin/npm-release-check.mjs" '{}' --no-tsc

trial mod-api-index --valid "$LF_API" \
    --expect missing-file=reject --expect empty-file=reject \
    --expect directory-as-file=reject --expect non-utf8-file=reject \
    --expect unknown-flag=reject --expect path-with-spaces=accept -- \
    node "$LF_REPOS/claude-code-mod-api/bin/mod-api-index.mjs" index '{}' "$out/index"

rm -rf "$out"
