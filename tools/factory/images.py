"""The trusted test image of the deterministic checks: content-derived tag and build-if-missing. Standard library only.

The tag is a hash of factory/test.Dockerfile and every file it copies, so any change to them names a new image and a
present tag is never a stale build. There is no cross-run cache: on a fresh runner the image is always built; on a
maintainer device an image with the current tag is reused."""
import argparse
import hashlib
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTEXT = "factory"
DOCKERFILE = "factory/test.Dockerfile"
REPOSITORY = "aicepeak-factory-test"
LABEL = "org.aicepeak.factory.test-inputs"
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
MAX_INPUT_BYTES = 2 * 1024 * 1024


class ImageError(ValueError):
    pass


def regular_file(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
        raise ImageError(f"expected a bounded regular file: {path}")
    return path.read_bytes()


def instructions(text):
    """Dockerfile instructions with continuation lines joined; comments and blank lines dropped."""
    joined, current = [], ""
    for line in text.splitlines():
        if not current and (not line.strip() or line.lstrip().startswith("#")):
            continue
        if line.rstrip().endswith("\\"):
            current += line.rstrip()[:-1] + " "
            continue
        joined.append((current + line).strip())
        current = ""
    if current:
        joined.append(current.strip())
    return joined


def test_image_inputs(root=ROOT):
    """factory/test.Dockerfile and every file its COPY instructions take from the build context, sorted.
    A source must be a regular file inside the context; globs, directories and escapes are refused."""
    context = (root / CONTEXT).resolve()
    sources = set()
    for instruction in instructions(regular_file(root / DOCKERFILE).decode()):
        words = shlex.split(instruction)
        if words[0].upper() != "COPY":
            continue
        arguments = [word for word in words[1:] if not word.startswith("--")]
        if any(word.startswith("--from") for word in words[1:]):
            continue
        if len(arguments) < 2:
            raise ImageError(f"unexpected COPY: {instruction}")
        for source in arguments[:-1]:
            path = (context / source).resolve()
            if any(char in source for char in "*?[") or not path.is_relative_to(context):
                raise ImageError(f"COPY source must be a file in {CONTEXT}/: {source}")
            regular_file(context / source)
            sources.add(f"{CONTEXT}/{path.relative_to(context).as_posix()}")
    return [DOCKERFILE, *sorted(sources - {DOCKERFILE})]


def test_image_digest(root=ROOT):
    """sha256 over the name, size and bytes of every input, so neither renaming nor moving bytes collides."""
    digest = hashlib.sha256()
    for name in test_image_inputs(root):
        data = regular_file(root / name)
        digest.update(name.encode() + b"\0" + str(len(data)).encode() + b"\0" + data)
    return digest.hexdigest()


def test_image_tag(root=ROOT):
    return f"{REPOSITORY}:{test_image_digest(root)[:16]}"


def docker_env():
    return {key: value for key, value in os.environ.items() if key in ("PATH", "DOCKER_HOST", "DOCKER_CONFIG")}


def inspect(tag, run):
    """(image ID, input label) of a present image, or None."""
    result = run(["docker", "image", "inspect", "--format", "{{.Id}} {{index .Config.Labels \"" + LABEL + "\"}}", tag],
                 capture_output=True, text=True, timeout=30, env=docker_env())
    if result.returncode != 0:
        return None
    image_id, _, label = result.stdout.strip().partition(" ")
    return image_id, label


def ensure_test_image(root=ROOT, run=subprocess.run, timeout=600, clock=time.monotonic):
    """Return (image ID, tag, built, seconds). Reuse the image with the current tag when its label carries exactly the
    current input digest; otherwise build it from the trusted context. Callers run the image by its ID."""
    digest = test_image_digest(root)
    tag = f"{REPOSITORY}:{digest[:16]}"
    present = inspect(tag, run)
    built, started = False, clock()
    if not present or present[1] != digest:
        result = run(["docker", "build", "--quiet", "-t", tag, "--label", f"{LABEL}={digest}",
                      "-f", str(root / DOCKERFILE), str(root / CONTEXT)],
                     capture_output=True, text=True, timeout=timeout, env=docker_env())
        if result.returncode != 0:
            raise ImageError("test image build failed: " + (result.stderr or result.stdout)[-2000:].strip())
        built, present = True, inspect(tag, run)
    if not present or not IMAGE_ID.fullmatch(present[0]) or present[1] != digest:
        raise ImageError("invalid test image identity")
    return present[0], tag, built, round(clock() - started, 1)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("test-tag", help="print the content-derived tag of the test image")
    sub.add_parser("ensure-test", help="build the test image if its tag is missing; print its image ID")
    args = parser.parse_args(argv)
    try:
        if args.command == "test-tag":
            print(test_image_tag())
            return 0
        print("Checking the test image (the first build takes a few minutes)...", file=sys.stderr)
        image_id, tag, built, seconds = ensure_test_image()
        print(f"test image {tag}: " + (f"built in {seconds} s" if built else "present"), file=sys.stderr)
        print(image_id)
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
