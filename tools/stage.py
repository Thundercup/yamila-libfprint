#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Create a new unprivileged installation staging tree; never modify host paths."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'runtime'))
from assets import DLL_NAME, check_runtime

RUNTIME_FILES = ('assets.py','bridge.py','native_bridge.py','protocol.py','usb_transport.py','broker.py',
                 'engine-guard','native-worker','vendor/'+DLL_NAME,'vendor/source.json','vendor/LICENSE-NOTICE.md')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, default=ROOT/'build')
    parser.add_argument('--destdir', type=Path, required=True)
    args = parser.parse_args()
    build = args.build_dir.resolve()
    dest = args.destdir.absolute()
    if dest == Path('/') or dest.exists() or dest.is_symlink():
        parser.error('--destdir must be a new directory')
    config = json.loads((build/'build-config.json').read_text())
    if config['test_mode']:
        parser.error('test-mode build is not installable; create a separate production-path build')
    check_runtime(build/'runtime')
    files = {}
    prefix = Path(config['prefix']).relative_to('/')
    libroot = prefix/config['libdir']
    execroot = Path(config['runtime_install']).relative_to('/')
    library = 'libfprint-2.so.2.0.0'
    # Use Meson's install copy so build-only dependency RUNPATH is removed.
    files[str(libroot/library)] = build/'libfprint-build/libfprint'/library
    for name in RUNTIME_FILES:
        files[str(execroot/name)] = build/'runtime'/name
    for name in ('README.md','NOTICE.md','vendor/LICENSE-NOTICE.md','vendor/source.json',
                 'LICENSES/LGPL-2.1-or-later.txt','packaging/INSTALL.md','docs/UBUNTU.md'):
        files[str(prefix/'share/doc/yamila-libfprint'/name)] = ROOT/name
    for name in files:
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('staged asset path must stay under destdir')
    install_temp=tempfile.TemporaryDirectory(prefix='yamila-rpath-stage-')
    subprocess.run(['meson','install','-C',str(build/'libfprint-build'),'--no-rebuild','--quiet','--destdir',install_temp.name],check=True)
    files[str(libroot/library)] = Path(install_temp.name)/libroot/library
    dest.mkdir(mode=0o755)
    manifest = dict(schema=1, config=config, files=[])
    for name, src in sorted(files.items()):
        path = dest/name
        path.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(src,path)
        mode = 0o755 if path.name in ('engine-guard','native-worker',library) else 0o644
        path.chmod(mode)
        manifest['files'].append(dict(path=name, mode=oct(mode), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    for name, target in [('libfprint-2.so.2',library),('libfprint-2.so','libfprint-2.so.2')]:
        (dest/libroot/name).symlink_to(target)
        manifest['files'].append(dict(path=str(libroot/name),symlink=target))
    (dest/'stage-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    install_temp.cleanup()
    print('Staged only: '+str(dest))


if __name__ == '__main__':
    main()
