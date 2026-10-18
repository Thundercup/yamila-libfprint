#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Run synthetic checks; opt into no-image vendor initialization separately."""
import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, default=ROOT/'build')
    parser.add_argument('--native', action='store_true', help='run DLL lifecycle checks without images or USB')
    args = parser.parse_args()
    build = args.build_dir.resolve()
    config = json.loads((build/'build-config.json').read_text())
    if not config['test_mode']:
        parser.error('libfprint API checks require a --test-mode build')
    env = {**os.environ, 'YML_RUNTIME_DIR':str(build/'runtime'),
           'YML_TEST_BINARY':str(build/'libfprint-build/tests/test-yamila')}
    subprocess.run(['meson','test','-C',str(build/'libfprint-build'),'yamila-prototype','--print-errorlogs'],check=True,env=env)
    subprocess.run(['/usr/bin/python3','-B',str(ROOT/'packaging/debian/test_preflight.py')],check=True,env=env)
    subprocess.run(['/usr/bin/python3','-B',str(ROOT/'tests/test_privacy.py')],check=True,env=env)
    subprocess.run(['/usr/bin/python3','-B',str(ROOT/'packaging/debian/test_pam_integration.py')],check=True,env=env)
    suites = ['PipelineTests']
    if args.native:
        suites.append('NativeLifecycleTests')
    subprocess.run(['/usr/bin/python3','-B',str(ROOT/'tests/test_pipeline.py'),*suites],check=True,env=env)
    subprocess.run(['/usr/bin/python3','-B',str(ROOT/'tests/test_assets.py')],check=True,env=env)
    subprocess.run(['/usr/bin/python3','-B',str(ROOT/'tests/test_audit.py')],check=True,env=env)
    subprocess.run(['/usr/bin/python3','-B',str(ROOT/'tests/test_release.py')],check=True,env=env)
    subprocess.run(['/usr/bin/python3','-B',str(ROOT/'packaging/tests/test_preflight.py')],check=True,env=env)
    subprocess.run(['/usr/bin/python3','-B',str(ROOT/'packaging/tests/test_selinux.py')],check=True,env=env)


if __name__ == '__main__':
    main()
