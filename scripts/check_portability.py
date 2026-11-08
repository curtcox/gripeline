#!/usr/bin/env python3
"""Verify the declared native baseline and portable gallery with a pinned t256.

Runs in the CI OS matrix; deliberately separate from network-free make check.
Use --release-dir for an already downloaded, checksum-verified release cache.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import gripeline as gl
import run as harness


def published_fixture(payload):
    """Admit only the reviewed count fixture for manual public-save acceptance."""
    document = json.loads(payload)
    if not isinstance(document, dict) or document.get('format') != 'hashbin-diagram' or document.get('version') != 1:
        raise RuntimeError('Published acceptance input must be a diagram envelope')
    case = harness.parse_case(ROOT / 'tests/cases/portable_t256_count.case')
    source = document.get('src')
    if not isinstance(source, str) or source.strip() not in (case.dot.strip(), case.modl.strip()):
        raise RuntimeError('Published acceptance input must match the portable count fixture exactly')
    return case


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--release-dir', type=Path)
    parser.add_argument('--published-cid', default=os.environ.get('GRIPELINE_PUBLISHED_CID', ''))
    args = parser.parse_args()
    environment = {'Darwin': 'macos', 'Linux': 'linux', 'Windows': 'windows'}[platform.system()]
    system = {'macos': 'darwin', 'linux': 'linux', 'windows': 'windows'}[environment]
    machine = platform.machine().lower()
    architecture = {'amd64': 'amd64', 'x86_64': 'amd64', 'arm64': 'arm64', 'aarch64': 'arm64', 'i386': '386', 'i686': '386'}[machine]
    asset = f't256-{system}-{architecture}' + ('.exe' if system == 'windows' else '')
    lock = json.loads((ROOT / 'scripts/t256-release.json').read_text(encoding='utf-8'))
    def load(name):
        if args.release_dir:
            return (args.release_dir / name).read_bytes()
        url = f"https://github.com/{lock['repo']}/releases/download/{lock['release']}/{name}"
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.read()
    sums = load('SHA256SUMS')
    if hashlib.sha256(sums).hexdigest() != lock['sumsSha256']:
        raise RuntimeError('Release checksum list did not match its pin')
    checks = {line.split()[1].lstrip('*'): line.split()[0] for line in sums.decode().splitlines()}
    binary = load(asset)
    if checks[asset] != lock['assets'][asset] or hashlib.sha256(binary).hexdigest() != checks[asset]:
        raise RuntimeError('Release binary did not match its pin')
    inventory = json.loads((ROOT / 'web/portable-tools.json').read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='gripeline-portable-') as directory:
        stage = Path(directory)
        executable = stage / ('t256.exe' if system == 'windows' else 't256')
        executable.write_bytes(binary)
        executable.chmod(0o755)
        config = stage / 'config.json'
        config.write_text(json.dumps({'providers': {'local': {'type': 'dir', 'path': str(stage / 'store'), 'create': True}}, 'sources': ['local'], 'destination': 'local'}), encoding='utf-8')
        env = dict(os.environ, PATH=str(stage) + os.pathsep + os.environ['PATH'], T256_CONFIG=str(config), PYTHONUTF8='1')
        def command(argv, **kwargs):
            return subprocess.run(argv, env=env, capture_output=True, text=True, encoding='utf-8', **kwargs)
        for tool in inventory['common'] + inventory['environments'][environment]:
            result = command([gl.locate_bash(), '-c', 'command -v ' + shlex.quote(tool)])
            if result.returncode:
                raise RuntimeError(f'{environment} baseline tool missing: {tool}')
        count = 0
        for path in sorted((ROOT / 'tests/cases').glob('portable_*.case')):
            case = harness.parse_case(path)
            builds = []
            for lang in ('dot', 'modl'):
                source = getattr(case, lang)
                api = gl.gripeline_api(source, lang, portable=True)
                if api['problems'] or api['warnings']:
                    raise RuntimeError(f'{case.name}: unexpected diagnostics: {api}')
                builds.append(api['bash'])
                file = stage / ('pipeline.' + lang)
                file.write_text(source, encoding='utf-8', newline='\n')
                result = command([sys.executable, str(ROOT / 'gripeline.py'), 'run', str(file)])
                expected = case.sections['stdout'].strip()
                if result.returncode or result.stdout.strip() != expected:
                    raise RuntimeError(f'{case.name} ({lang}): {result.returncode}, {result.stdout!r}, {result.stderr!r}')
                count += 1
            if builds[0] != builds[1]:
                raise RuntimeError(f'{case.name}: dot/modl bash differs')
        # Exercise a non-inline hashbin-diagram envelope in a real local store.
        payload = json.dumps({'format': 'hashbin-diagram', 'version': 1, 'src': 'a square printf portable', 'pos': {}})
        saved = command([str(executable), 'save', '-f', 't256', '-'], input=payload)
        if saved.returncode:
            raise RuntimeError(saved.stderr)
        reference = saved.stdout.strip()
        result = command([sys.executable, str(ROOT / 'gripeline.py'), 'run', reference])
        if result.returncode or result.stdout != 'portable':
            raise RuntimeError(f'CID envelope run failed: {result.stderr}')
        # Verified loading must prevent tampered source from reaching execution.
        (stage / 'store' / gl.cid_reference(reference)).write_text('tampered', encoding='utf-8')
        result = command([sys.executable, str(ROOT / 'gripeline.py'), 'run', reference])
        if result.returncode != 2 or result.stdout:
            raise RuntimeError('Tampered CID input was not rejected before execution')
        print(f'{environment}: baseline tools, {count} portable twin executions, CID envelope round trip and tamper rejection passed')
        if args.published_cid:
            cid = gl.cid_reference(args.published_cid)
            if int.from_bytes(base64.urlsafe_b64decode(cid[:8]), 'big') > 1048576:
                raise RuntimeError('Published acceptance input exceeds 1 MiB')
            config.write_text(json.dumps({'providers': {'public': {'type': 'http', 'url': 'https://256t.us'}}, 'sources': ['public'], 'timeout': '30s'}), encoding='utf-8')
            loaded = command([str(executable), 'load', cid])
            if loaded.returncode:
                raise RuntimeError(loaded.stderr)
            case = published_fixture(loaded.stdout)
            result = command([sys.executable, str(ROOT / 'gripeline.py'), 'run', 't256:' + cid])
            if result.returncode or result.stdout.strip() != case.sections['stdout'].strip():
                raise RuntimeError(f'Published CID run failed: {result.stdout!r}, {result.stderr}')
            print(f'{environment}: approved public CID save → copy → run passed (output 6)')


if __name__ == '__main__':
    main()
