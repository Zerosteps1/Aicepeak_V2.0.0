#!/usr/bin/env bash
# Install the global `factory` command on this device (docs/factory-cli.md#install).
#
# Stage 1 (this script) checks the prerequisites, refuses to run unless it is byte-identical to the copy on
# origin/main, and clones the control checkout if it is missing. Stage 2 runs from that control checkout:
#   factory.py _install  (tools/factory/cli/install.py)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repo="$(git -C "$here" rev-parse --show-toplevel)"
parent="$(dirname "$repo")"
control="$parent/aicepeak-control-checkout"
candidate="$parent/aicepeak-candidate"
bin="$HOME/.local/bin"
keys=""

usage() {
  cat <<EOF
Usage: $0 [--control-dir DIR] [--candidate-dir DIR] [--bin-dir DIR] [--author-keys]

  --control-dir DIR    control checkout (default: $control)
  --candidate-dir DIR  candidate checkout; an existing clone is reused (default: $candidate)
  --bin-dir DIR        where the factory command goes (default: $bin)
  --author-keys        (re)store the Anthropic and Context7 API keys in the macOS keychain
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --control-dir) control="$2"; shift 2 ;;
    --candidate-dir) candidate="$2"; shift 2 ;;
    --bin-dir) bin="$2"; shift 2 ;;
    --author-keys) keys="--author-keys"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for tool in git gh python3; do
  command -v "$tool" >/dev/null 2>&1 || { echo "missing $tool: see docs/dev-setup.md" >&2; exit 1; }
done
python="$(command -v python3)"
"$python" -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo "Python 3.11 or newer is required" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || echo "note: gh is not logged in; most factory commands need \`gh auth login\`" >&2

# Fixed here, so the byte-identity check below also covers where the control checkout comes from.
repository="Zerosteps1/Aicepeak_V2.0.0"
configured="$("$python" -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["repository"])' "$repo/factory/config.json")"
[ "$configured" = "$repository" ] || { echo "factory/config.json names $configured, not $repository; refusing" >&2; exit 1; }
url="https://github.com/$repository.git"
self="tools/factory/cli/install-factory-cli.sh"

# Only the reviewed installer from main may continue.
git -C "$repo" -c core.hooksPath=/dev/null fetch --quiet --no-tags "$url" +refs/heads/main:refs/remotes/origin/main
expected="$(git -C "$repo" rev-parse --verify --quiet "refs/remotes/origin/main:$self")" \
  || { echo "origin/main has no $self yet" >&2; exit 1; }
actual="$(git -C "$repo" hash-object --no-filters "$here/install-factory-cli.sh")"
[ "$expected" = "$actual" ] \
  || { echo "this installer differs from origin/main; run the copy of an up-to-date main checkout" >&2; exit 1; }

if [ ! -e "$control" ]; then
  git -c core.hooksPath=/dev/null clone --quiet --branch main "$url" "$control"
else
  # Stage 2 must come from current main: fast-forward a clean existing control checkout first.
  git -C "$control" -c core.hooksPath=/dev/null fetch --quiet --no-tags "$url" +refs/heads/main:refs/remotes/origin/main
  head="$(git -C "$control" rev-parse HEAD)"
  main="$(git -C "$control" rev-parse refs/remotes/origin/main)"
  if [ "$head" != "$main" ]; then
    if [ -z "$(git -C "$control" -c core.fsmonitor=false status --porcelain --ignored)" ] \
        && git -C "$control" merge-base --is-ancestor "$head" "$main"; then
      git -C "$control" -c core.hooksPath=/dev/null merge --ff-only --quiet "$main"
    else
      echo "control checkout $control is not a clean clone of main; fix it or choose another --control-dir" >&2
      exit 1
    fi
  fi
fi
exec "$python" -I -S -B "$control/tools/factory/cli/factory.py" _install \
  --control-dir "$control" --candidate-dir "$candidate" --bin-dir "$bin" $keys
