#!/bin/sh
# Run the factory's checks the way the pipeline does: in the trusted test image (factory/test.Dockerfile, built if its
# content-derived tag is missing), with a read-only root filesystem, no network and a throwaway copy of the files Git
# sees in this working tree (tracked and untracked, uncommitted changes included; ignored files such as node_modules,
# bin/obj and .env and the .git folder left out), so nothing is ever written into the repository
# (docs/dev-setup.md#test-changes-in-the-sandbox).
#   tools/factory/sandbox-verify.sh                  full verify.py --ci; ends with four PASS lines
#   tools/factory/sandbox-verify.sh 'test_cli*.py'   only the unit tests whose file names match the pattern
set -eu
root="$(cd "$(dirname "$0")/../.." && pwd -P)"
image="$(python3 -E -s -B "$root/tools/factory/images.py" test-tag)"
[ -n "$image" ] || { echo "cannot read the test image tag from tools/factory/images.py" >&2; exit 1; }
# As `factory` does: start a stopped Docker Desktop and wait up to 120 s. A present image is woken once with a no-op
# container (Docker Desktop's resource saver answers queries without the VM and may call a present image missing).
waited=0 started=
until docker info >/dev/null 2>&1; do
  [ -n "$started" ] || [ -n "${FACTORY_DOCKER_HOST:-}" ] \
    || { started=1; echo "Starting Docker Desktop..." >&2; docker desktop start --timeout 120 >/dev/null 2>&1 || true; continue; }
  [ "$waited" -eq 0 ] && echo "Waiting for Docker to be ready, up to 120 s..." >&2
  [ "$waited" -ge 120 ] && { echo "Docker is not running; see \`factory doctor\`" >&2; exit 1; }
  sleep 2; waited=$((waited + 2))
done
docker image inspect "$image" >/dev/null 2>&1 \
  || docker run --rm --pull never --network none --cap-drop ALL --read-only --entrypoint true "$image" >/dev/null 2>&1 || true
image_id="$(python3 -E -s -B "$root/tools/factory/images.py" ensure-test)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
trap 'exit 130' INT TERM
mkdir "$work/candidate"
git -C "$root" ls-files -z --cached --others --exclude-standard \
  | rsync -a --from0 --files-from=- --ignore-missing-args --exclude .DS_Store --exclude __pycache__ "$root/" "$work/candidate/"
if [ $# -gt 0 ]; then
  # The pattern travels as an argument, never as shell text.
  set -- sh -c 'FACTORY_CANDIDATE=/candidate exec python3 -I -B -m unittest discover -s /candidate/tools/factory/tests -p "$1"' sh "$1"
else
  set -- python3 /candidate/tools/factory/verify.py --root /candidate --trusted-root /candidate --ci
fi
docker run --rm --init --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --pids-limit 256 --memory 2g --tmpfs /tmp:rw,nosuid,nodev,size=256m -e HOME=/tmp \
  --mount "type=bind,src=$work/candidate,dst=/candidate,readonly" --workdir /candidate "$image_id" "$@"
