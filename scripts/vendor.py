#!/usr/bin/env python3
"""Verify vendored assets, or fetch missing assets at their locked URLs."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1] / 'web' / 'vendor'


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--fetch', action='store_true')
    args = parser.parse_args()
    entries = json.loads((ROOT / 'vendor.lock.json').read_text())
    for item in entries:
        path = (ROOT / item['target']).resolve()
        if not path.is_relative_to(ROOT.resolve()):
            raise ValueError('vendor target escapes vendor directory')
        if args.fetch and not path.exists():
            data = urllib.request.urlopen(item['url'], timeout=60).read()
            if hashlib.sha256(data).hexdigest() != item['sha256']:
                raise ValueError('download hash mismatch: ' + item['target'])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('vendor hash mismatch: ' + item['target'])
    print(f'Verified {len(entries)} vendored files')


if __name__ == '__main__':
    main()
