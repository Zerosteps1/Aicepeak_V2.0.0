#!/bin/sh
# Run the factory's checks the way the pipeline does: in the author image, with a read-only root filesystem, no
# network and a throwaway copy of this working tree (uncommitted changes included, .git left out), so nothing is
# ever written into the repository (docs/dev-setup.md#test-changes-in-the-sandbox).
#   tools/factory/sandbox-verify.sh                  full verify.py --ci; ends with four PASS lines
#   tools/factory/sandbox-verify.sh 'test_cli*.py'   only the unit tests whose file names match the pattern
set -eu
root="$(cd "$(dirname "$0")/../.." && pwd -P)"
image="$(sed -n 's/^IMAGE = "\(.*\)"$/\1/p' "$root/tools/factory/clients.py")"
[ -n "$image" ] || { echo "cannot read IMAGE from tools/factory/clients.py" >&2; exit 1; }
# Docker Desktop starting up or waking from its resource saver answers late: wait up to 120 s, as `factory` does.
waited=0
until docker info >/dev/null 2>&1 && docker image inspect "$image" >/dev/null 2>&1; do
  [ "$waited" -eq 0 ] && echo "Waiting for Docker to be ready, up to 120 s (start Docker Desktop if it is not running)..." >&2
  [ "$waited" -ge 120 ] && { echo "the author image $image is missing or Docker is not running; see \`factory doctor\`" >&2; exit 1; }
  sleep 2; waited=$((waited + 2))
done
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
trap 'exit 130' INT TERM
rsync -a --exclude .git --exclude .DS_Store --exclude __pycache__ "$root/" "$work/candidate/"
if [ $# -gt 0 ]; then
  # The pattern travels as an argument, never as shell text.
  set -- sh -c 'FACTORY_CANDIDATE=/candidate exec python3 -I -B -m unittest discover -s /candidate/tools/factory/tests -p "$1"' sh "$1"
else
  set -- python3 /candidate/tools/factory/verify.py --root /candidate --trusted-root /candidate --ci
fi
docker run --rm --init --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --pids-limit 256 --memory 2g --tmpfs /tmp:rw,nosuid,nodev,size=256m -e HOME=/tmp \
  --mount "type=bind,src=$work/candidate,dst=/candidate,readonly" --workdir /candidate "$image" "$@"
