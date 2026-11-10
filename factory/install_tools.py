"""Install the exact, checksum-verified release binaries pinned in factory/tools.lock.json.

On Linux they go into the factory image; on a maintainer's Mac into the folder of the `factory` command,
which `factory doctor` prints."""
import argparse
import hashlib
import io
import json
import os
import platform
import sys
import tarfile
import urllib.request
from pathlib import Path

ARCH={'x86_64':'amd64','amd64':'amd64','aarch64':'arm64','arm64':'arm64'}


def platform_key(system=sys.platform,machine=None):
    machine=(machine or platform.machine()).lower()
    name='darwin' if system=='darwin' else 'linux' if system.startswith('linux') else None
    if name is None or machine not in ARCH:raise ValueError(f'no pinned tools for {system}/{machine}')
    return f'{name}_{ARCH[machine]}'


def install(lock,destination,key,only=(),fetch=None):
    fetch=fetch or (lambda url:urllib.request.urlopen(url,timeout=60))
    unknown=sorted(set(only)-set(lock))
    if unknown:raise ValueError('not in the lock: '+', '.join(unknown))
    destination.mkdir(parents=True,exist_ok=True)
    installed=[]
    for name,item in lock.items():
        if only and name not in only:continue
        if key not in item:raise ValueError(f'no pinned {name} for {key}')
        asset=item[key]
        url=f"https://github.com/{item['repository']}/releases/download/v{item['version']}/{asset['asset']}"
        with fetch(url) as response:data=response.read(30_000_001)
        if len(data)>30_000_000 or hashlib.sha256(data).hexdigest()!=asset['sha256']:raise ValueError('tool digest mismatch: '+name)
        with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
            member=archive.getmember(name)
            if not member.isfile() or member.size>100_000_000:raise ValueError('unsafe tool member')
            content=archive.extractfile(member).read()
        # Replace the file itself, never write through a symlink that points at another installation.
        output,part=destination/name,destination/f'.{name}.part'
        part.write_bytes(content);part.chmod(0o755);os.replace(part,output)
        installed.append(output)
    return installed


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--lock',type=Path,required=True);p.add_argument('--destination',type=Path,required=True)
    p.add_argument('--only',action='append',default=[],help='install only this tool (repeatable)')
    args=p.parse_args(argv)
    try:
        for path in install(json.loads(args.lock.read_text()),args.destination,platform_key(),args.only):print(f'installed {path}')
    except (OSError,ValueError,KeyError,tarfile.TarError) as exc:
        print(f'BLOCKED: {exc}',file=sys.stderr);return 1
    return 0


if __name__=='__main__':sys.exit(main())
