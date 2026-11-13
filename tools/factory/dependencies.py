"""Trusted dependency fetch for the product checks. Standard library only, trusted host code; runs no PR code.

npm: the host checks package.json and package-lock.json (registry sources with sha512 integrity only), then `npm ci
--ignore-scripts` runs in a fetch container from the test image that sees only copies of those two files: no project
.npmrc, no scripts, no credentials. npm verifies every tarball against the lock's integrity.

NuGet: the host reads backend/**/packages.lock.json and downloads every pinned package by exact id and version from the
nuget.org flat container into a flat folder feed. The sandbox restores offline from that feed in locked mode, where
NuGet checks each package against the lock file's content hash."""
import http.client
import json
import os
import threading
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import sandbox

NPM_REGISTRY = 'https://registry.npmjs.org/'
NUGET_FLAT = 'https://api.nuget.org/v3-flatcontainer/'
MAX_NPM_PACKAGE = 1024 * 1024
MAX_NPM_LOCK = 5 * 1024 * 1024
MAX_NPM_ENTRIES = 3000
MAX_NUGET_LOCKS = 20
MAX_NUGET_LOCK = 2 * 1024 * 1024
MAX_NUGET_PACKAGES = 500
MAX_PACKAGE_BYTES = 100 * 1024 * 1024
MAX_FEED_BYTES = 1536 * 1024 * 1024
INTEGRITY = re.compile(r'sha512-[A-Za-z0-9+/]{86}==')
NPM_PATH = re.compile(r'(?:node_modules/(?:@[^/.][^/]*/)?[^/.][^/]*/)*node_modules/(?:@[^/.][^/]*/)?[^/.][^/]*')
DEPENDENCY_FIELDS = ('dependencies', 'devDependencies', 'optionalDependencies', 'peerDependencies', 'overrides')
NUGET_ID = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}')
NUGET_VERSION = re.compile(r'[0-9]+(?:\.[0-9]+){1,3}(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?')
CONTENT_HASH = re.compile(r'[A-Za-z0-9+/]{86}==')
NUGET_TYPES = ('Direct', 'Transitive', 'CentralTransitive', 'Project')
SKIPPED_DIRECTORIES = ('bin', 'obj', 'node_modules', '.git')


class DependencyError(ValueError):
    pass


def load_json(data, limit, name):
    if len(data) > limit:
        raise DependencyError(f'{name} too large')
    try:
        return json.loads(data)
    except (ValueError, UnicodeDecodeError):
        raise DependencyError(f'{name} is not valid JSON') from None


def registry_specifiers(value, field):
    """Every version specifier in a dependency field (overrides may nest objects) must be a plain registry range."""
    if isinstance(value, dict):
        for item in value.values():
            registry_specifiers(item, field)
    elif not isinstance(value, str) or ':' in value or '/' in value or value.endswith('.tgz'):
        raise DependencyError(f'package.json {field}: only registry version specifiers are allowed, not {str(value)[:80]!r}')


def npm_check(package_json, package_lock):
    """Refuse anything that would make npm fetch from outside the registry or without sha512 integrity."""
    package = load_json(package_json, MAX_NPM_PACKAGE, 'package.json')
    lock = load_json(package_lock, MAX_NPM_LOCK, 'package-lock.json')
    if not isinstance(package, dict) or not isinstance(lock, dict):
        raise DependencyError('package.json and package-lock.json must be JSON objects')
    if 'workspaces' in package:
        raise DependencyError('npm workspaces are not supported by the factory')
    for field in DEPENDENCY_FIELDS:
        registry_specifiers(package.get(field, {}), field)
    if lock.get('lockfileVersion') not in (2, 3):
        raise DependencyError('package-lock.json lockfileVersion must be 2 or 3')
    packages = lock.get('packages')
    if not isinstance(packages, dict) or len(packages) > MAX_NPM_ENTRIES:
        raise DependencyError('package-lock.json packages missing or too many')
    for key, entry in packages.items():
        if key == '':
            continue
        if not NPM_PATH.fullmatch(key) or '..' in key.split('/'):
            raise DependencyError(f'unexpected package path in package-lock.json: {key[:80]!r}')
        if not isinstance(entry, dict) or entry.get('link'):
            raise DependencyError(f'package-lock.json {key!r}: link entries are not allowed')
        if entry.get('inBundle'):
            # Extracted from its parent's verified tarball: npm downloads it on its own only if no parent bundles it,
            # so it must sit inside a parent entry and carry no source of its own.
            parent = key.rsplit('/node_modules/', 1)[0]
            if '/node_modules/' not in key or parent not in packages or any(field in entry for field in ('resolved', 'integrity', 'link')):
                raise DependencyError(f'package-lock.json {key!r}: bundled entries must be nested in their parent and have no source')
            continue
        resolved = entry.get('resolved')
        if not isinstance(resolved, str) or not resolved.startswith(NPM_REGISTRY) or '?' in resolved or '#' in resolved:
            raise DependencyError(f'package-lock.json {key!r}: resolved must be a registry.npmjs.org tarball')
        if not isinstance(entry.get('integrity'), str) or not INTEGRITY.fullmatch(entry['integrity']):
            raise DependencyError(f'package-lock.json {key!r}: integrity must be sha512')


def npm_fetch_argv(image_id, deps, name, user):
    """The fetch container: same image and limits as the sandbox, but with network, a larger tmpfs for npm's cache,
    and only /deps (copies of package.json and package-lock.json) mounted. No PR code runs here."""
    command = sandbox.argv(image_id, ['npm', 'ci', '--ignore-scripts', '--no-audit', '--no-fund', '--include=dev',
                                      '--registry=' + NPM_REGISTRY], name, mounts=[(deps, '/deps', False)],
                           env={'npm_config_userconfig': '/tmp/no-user-npmrc', 'npm_config_globalconfig': '/tmp/no-global-npmrc',
                                'NO_COLOR': '1'}, workdir='/deps', user=user)
    command[command.index('--network') + 1] = 'bridge'
    command[command.index('--tmpfs') + 1] = '/tmp:rw,nosuid,nodev,size=512m'
    return command


def nuget_lock_files(candidate):
    root, found = Path(candidate) / 'backend', []
    for directory, subdirectories, files in os.walk(root, followlinks=False):
        subdirectories[:] = [name for name in subdirectories if name not in SKIPPED_DIRECTORIES]
        if 'packages.lock.json' in files:
            path = Path(directory) / 'packages.lock.json'
            relative = str(path.relative_to(candidate))
            if not sandbox.regular(candidate, relative) or path.stat().st_size > MAX_NUGET_LOCK:
                raise DependencyError(f'{relative} must be a regular file of at most 2 MiB')
            found.append(path)
    if not found or len(found) > MAX_NUGET_LOCKS:
        raise DependencyError('backend needs committed packages.lock.json files '
                              '(dotnet restore backend/Aicepeak.slnx --force-evaluate)')
    return sorted(found)


def nuget_packages(candidate):
    """(id, version), lower-case and unique, of every package pinned in backend/**/packages.lock.json."""
    hashes = {}
    for path in nuget_lock_files(candidate):
        lock = load_json(path.read_bytes(), MAX_NUGET_LOCK, str(path.relative_to(candidate)))
        if not isinstance(lock, dict) or lock.get('version') != 2 or not isinstance(lock.get('dependencies'), dict):
            raise DependencyError(f'{path.relative_to(candidate)}: lock file version 2 expected')
        for framework in lock['dependencies'].values():
            if not isinstance(framework, dict):
                raise DependencyError('unexpected lock file layout')
            for name, entry in framework.items():
                if not isinstance(entry, dict) or entry.get('type') not in NUGET_TYPES:
                    raise DependencyError(f'{name[:80]!r}: unexpected lock entry type')
                if entry['type'] == 'Project':
                    continue
                if not NUGET_ID.fullmatch(name) or '..' in name:
                    raise DependencyError(f'unexpected package name {name[:80]!r}')
                version, content_hash = entry.get('resolved'), entry.get('contentHash')
                if not isinstance(version, str) or not NUGET_VERSION.fullmatch(version):
                    raise DependencyError(f'{name}: unexpected version {str(version)[:40]!r}')
                if not isinstance(content_hash, str) or not CONTENT_HASH.fullmatch(content_hash):
                    raise DependencyError(f'{name}: contentHash must be a base64 SHA-512')
                key = (name.lower(), version.lower())
                if hashes.setdefault(key, content_hash) != content_hash:
                    raise DependencyError(f'{name} {version}: conflicting content hashes in the lock files')
    if len(hashes) > MAX_NUGET_PACKAGES:
        raise DependencyError('too many NuGet packages')
    return sorted(hashes)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # urllib then raises HTTPError with the 3xx code


def opener():
    return urllib.request.build_opener(NoRedirect())


class Budget:
    """Shared limits of one fetch: total bytes and wall-clock time, checked by every download."""
    def __init__(self, feed_bytes, seconds, clock):
        self.left, self.end, self.clock, self.lock = feed_bytes, clock() + seconds, clock, threading.Lock()

    def timeout(self, limit):
        remaining = self.end - self.clock()
        if remaining <= 0:
            raise DependencyError('NuGet fetch exceeded the time budget')
        return min(limit, remaining)

    def take(self, size):
        with self.lock:
            self.left -= size
            if self.left < 0:
                raise DependencyError('NuGet packages exceed the feed size limit')


def download(url, target, opener, max_bytes, timeout):
    with opener.open(url, timeout=timeout) as response:
        if getattr(response, 'status', 200) != 200:
            raise DependencyError(f'unexpected status {response.status} for {url}')
        data = response.read(max_bytes + 1)
        expected = (getattr(response, 'headers', None) or {}).get('Content-Length')
    if len(data) > max_bytes:
        raise DependencyError(f'{url} is too large')
    if expected is not None and str(expected).isdigit() and int(expected) != len(data):
        raise ConnectionError('truncated download')
    target.write_bytes(data)
    return len(data)


def fetch_package(package, feed, opener, max_bytes, timeout, sleep, budget, attempts=3):
    name, version = package
    url = NUGET_FLAT + '/'.join(urllib.parse.quote(part) for part in (name, version, f'{name}.{version}.nupkg'))
    for attempt in range(attempts):
        try:
            size = download(url, Path(feed) / f'{name}.{version}.nupkg', opener, max_bytes, budget.timeout(timeout))
            budget.take(size)
            return size
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise DependencyError(f'{name} {version} is not on nuget.org') from None
            if 300 <= exc.code < 400:
                raise DependencyError(f'unexpected redirect for {name} {version}') from None
            if exc.code < 500 or attempt == attempts - 1:
                raise DependencyError(f'nuget.org unavailable: HTTP {exc.code} for {name} {version}') from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, http.client.HTTPException) as exc:
            if attempt == attempts - 1:
                raise DependencyError(f'nuget.org unavailable: {type(exc).__name__} for {name} {version}') from None
        sleep(2 ** attempt)


def fetch_nuget(packages, feed, opener=None, max_bytes=MAX_PACKAGE_BYTES, timeout=60, sleep=time.sleep, workers=4,
                feed_bytes=MAX_FEED_BYTES, seconds=600, clock=time.monotonic):
    """Download every package into the flat folder `feed`, within a total size and time budget; the first failure stops
    the rest. Integrity is NuGet's: the sandbox restores in locked mode."""
    Path(feed).mkdir(parents=True, exist_ok=True)
    opener, budget = opener or globals()['opener'](), Budget(feed_bytes, seconds, clock)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return sum(pool.map(lambda package: fetch_package(package, feed, opener, max_bytes, timeout, sleep, budget), packages))


def write_nuget_config(feeds):
    """The restore configuration the sandbox uses instead of the candidate's nuget.config: one local source."""
    path = Path(feeds) / 'nuget.config'
    path.write_text('<?xml version="1.0" encoding="utf-8"?>\n<configuration>\n'
                    '  <packageSources>\n    <clear />\n    <add key="factory-offline" value="/feeds/nuget" />\n  </packageSources>\n'
                    '  <auditSources>\n    <clear />\n  </auditSources>\n</configuration>\n')
    return path

