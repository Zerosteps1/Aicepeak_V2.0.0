"""Install the exact checksum-verified release binaries into a factory image."""
import argparse
import hashlib
import io
import json
import platform
import tarfile
import urllib.request
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--lock',type=Path,required=True);p.add_argument('--destination',type=Path,required=True)
    args=p.parse_args();lock=json.loads(args.lock.read_text())
    arch={'x86_64':'amd64','aarch64':'arm64'}[platform.machine()]
    args.destination.mkdir(parents=True,exist_ok=True)
    for name,item in lock.items():
        asset=item['linux_'+arch]
        url=f"https://github.com/{item['repository']}/releases/download/v{item['version']}/{asset['asset']}"
        with urllib.request.urlopen(url,timeout=60) as response:data=response.read(30_000_001)
        if len(data)>30_000_000 or hashlib.sha256(data).hexdigest()!=asset['sha256']:raise ValueError('tool digest mismatch: '+name)
        with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
            member=archive.getmember(name)
            if not member.isfile() or member.size>100_000_000:raise ValueError('unsafe tool member')
            output=args.destination/name;output.write_bytes(archive.extractfile(member).read());output.chmod(0o755)


if __name__=='__main__':main()
