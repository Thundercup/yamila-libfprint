#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Build pinned libfprint and a sibling worker runtime; never install to host."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import shlex
import os
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'runtime'))
from assets import validate_dll, DLL_NAME


def run(args):
    subprocess.run([str(a) for a in args], check=True)


def checked_archive(path, lock):
    if hashlib.sha256(path.read_bytes()).hexdigest() != lock['sha256']:
        raise ValueError('libfprint archive SHA-256 mismatch')
    return path


def replace_once(path, old, new):
    text = path.read_text()
    if text.count(old) != 1:
        raise ValueError('pinned upstream source layout mismatch: '+path.name)
    path.write_text(text.replace(old, new, 1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream-archive', type=Path)
    parser.add_argument('--fetch-upstream', action='store_true')
    parser.add_argument('--build-dir', type=Path, default=ROOT/'build')
    parser.add_argument('--prefix', default='/usr')
    parser.add_argument('--libdir', default='lib64')
    parser.add_argument('--libexecdir', default='libexec')
    parser.add_argument('--worker-user', default='yamila-fprint')
    parser.add_argument('--test-mode', action='store_true', help='enable synthetic virtual driver; not installable')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,30}', args.worker_user):
        raise ValueError('invalid worker account name')
    for directory in (args.prefix, args.libdir, args.libexecdir):
        if not directory or '..' in Path(directory).parts or '"' in directory or '\\' in directory:
            raise ValueError('invalid installation path')
    for directory in (args.libdir, args.libexecdir):
        if Path(directory).is_absolute() or not Path(directory).parts or directory == '.':
            raise ValueError('libdir and libexecdir must be relative subdirectories')
    if not Path(args.prefix).is_absolute():
        raise ValueError('prefix must be absolute')
    validate_dll(ROOT/'vendor'/DLL_NAME)  # Fail before compilation or any USB I/O.
    lock = json.loads((ROOT/'upstream.lock.json').read_text())
    archive = args.upstream_archive
    if archive is None:
        archive = ROOT/'.cache'/lock['archive']
        if not archive.exists():
            if not args.fetch_upstream:
                raise ValueError('provide --upstream-archive or explicitly use --fetch-upstream')
            archive.parent.mkdir(parents=True, exist_ok=True)
            pending = archive.with_suffix('.download')
            try:
                with urllib.request.urlopen(lock['url'], timeout=60) as src, pending.open('xb') as dst:
                    shutil.copyfileobj(src, dst)
                checked_archive(pending, lock)
                pending.replace(archive)
            finally:
                pending.unlink(missing_ok=True)
    archive = checked_archive(archive.resolve(strict=True), lock)
    build = args.build_dir.resolve()
    build.mkdir(parents=True, exist_ok=True)
    source = build/'libfprint-v1.94.100'
    runtime = build/'runtime'
    meta_path = build/'build-config.json'
    config = dict(schema=1, test_mode=args.test_mode, prefix=args.prefix, libdir=args.libdir,
                  libexecdir=args.libexecdir, worker_user=args.worker_user,
                  runtime_install=str(Path(args.prefix)/args.libexecdir/'yamila-fprint'))
    if meta_path.exists() and json.loads(meta_path.read_text()) != config:
        raise ValueError('build configuration changed: use a new build directory')
    if source.exists() and not meta_path.exists():
        raise ValueError('untracked upstream work tree: use a new build directory')
    if not source.exists():
        with tarfile.open(archive) as tar:
            top = {Path(m.name).parts[0] for m in tar.getmembers()}
            if top != {'libfprint-v1.94.100'}:
                raise ValueError('unexpected upstream archive root')
            tar.extractall(build, filter='data')
        replace_once(source/'meson.build', 'drivers_info = {',
                     "drivers_info = {\n    'yamila': {},\n    'yamila_virtual': {'virtual': true, 'optional': true},")
        replace_once(source/'libfprint/meson.build', 'driver_sources = {',
                     "driver_sources = {\n    'yamila' : files('drivers/yamila.c'),\n    'yamila_virtual' : files('drivers/yamila_virtual.c'),")
        replace_once(source/'tests/meson.build', 'foreach driver_test: drivers_tests',
                     'foreach driver_test, ignored: drivers_tests')
        with (source/'tests/meson.build').open('a') as f:
            f.write("""
if 'yamila_virtual' in drivers
  yamila_test = executable('test-yamila', 'test-yamila.c', dependencies: libfprint_dep)
  test('yamila-prototype', yamila_test, timeout: 60,
       env: ['FP_DRIVERS_ALLOWLIST=yamila_virtual', 'G_DEBUG=fatal-warnings'])
endif
""")
        meta_path.write_text(json.dumps(config, indent=2)+'\n')
    runtime.mkdir(exist_ok=True)
    for path in (ROOT/'runtime').glob('*.py'):
        shutil.copyfile(path, runtime/path.name)
    (runtime/'vendor').mkdir(exist_ok=True)
    for name in (DLL_NAME, 'source.json', 'LICENSE-NOTICE.md'):
        shutil.copyfile(ROOT/'vendor'/name, runtime/'vendor'/name)
    for path in (ROOT/'driver').glob('*.c'):
        shutil.copyfile(path, source/'libfprint/drivers'/path.name)
    shutil.copyfile(ROOT/'tests/test-yamila.c', source/'tests/test-yamila.c')
    broker = runtime/'broker.py' if args.test_mode else Path(config['runtime_install'])/'broker.py'
    (source/'libfprint/drivers/yamila-paths.h').write_text(
        '#define YML_BROKER '+json.dumps(str(broker), ensure_ascii=False)+'\n'+
        '#define YML_WORKER_USER '+json.dumps(args.worker_user)+'\n')
    cflags=shlex.split(os.environ.get('CFLAGS',''))
    ldflags=shlex.split(os.environ.get('LDFLAGS',''))
    run(['gcc', '-std=gnu11', '-O1', '-g', *cflags, '-fno-strict-aliasing', '-maccumulate-outgoing-args',
         '-o', runtime/'native-worker', ROOT/'native/native_worker.c', *ldflags, '-lcrypto', '-lpthread'])
    run(['gcc', '-std=gnu11', '-O2', *cflags, '-Wall', '-Wextra', '-Werror',
         '-o', runtime/'engine-guard', ROOT/'native/engine_guard.c', *ldflags])
    meson = build/'libfprint-build'
    options = ['-Ddrivers=yamila,yamila_virtual' if args.test_mode else '-Ddrivers=yamila',
               '-Dintrospection=false', '-Ddoc=false', '-Dinstalled-tests=false',
               '-Dudev_rules=disabled', '-Dudev_hwdb=disabled',
               '--prefix='+args.prefix, '--libdir='+args.libdir, '--libexecdir='+args.libexecdir]
    if (meson/'build.ninja').exists():
        run(['meson', 'setup', '--reconfigure', '--clearcache', meson, source, *options])
    else:
        run(['meson', 'setup', meson, source, *options])
    run(['meson', 'compile', '-C', meson])
    print('Built '+('synthetic test' if args.test_mode else 'production-path')+' tree: '+str(build))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
