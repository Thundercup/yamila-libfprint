#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Build one CI platform and collect only reviewed release artifacts."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from audit import ROOT, audit
from build import checked_archive

def run(*args):subprocess.run([str(x) for x in args],check=True)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--platform',choices=['fedora44','ubuntu2604'],required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--upstream-archive',type=Path)
    a=p.parse_args();audit();run('python3','-B',ROOT/'tools/privacy_check.py')
    if a.output.exists():p.error('output must be new')
    archive=a.upstream_archive or Path('/tmp/libfprint-upstream.tar.gz')
    if not a.upstream_archive:run('python3','-B',ROOT/'tools/fetch_upstream.py','--dest',archive)
    checked_archive(archive,json.loads((ROOT/'upstream.lock.json').read_text()))
    if a.platform=='fedora44':
        work=Path('/tmp/yamila-rpmbuild')
        run('python3','-B',ROOT/'tools/rpm.py','--upstream-archive',archive,'--workdir',work,'--release','10','--container-build')
        artifacts=[*work.glob('RPMS/**/*.rpm'),*work.glob('SRPMS/*.rpm'),work/'SOURCES/yamila-libfprint-0.0.1.tar.gz']
        for item in work.glob('RPMS/**/*.rpm'):run('python3','-B',ROOT/'tools/inspect_rpm.py',item)
    else:
        work=Path('/tmp/yamila-deb')
        run('python3','-B',ROOT/'tools/deb.py','--upstream-archive',archive,'--workdir',work)
        artifacts=[*work.glob('*.deb'),*work.glob('*.tar.gz')]
        for item in work.glob('*.deb'):run('python3','-B',ROOT/'tools/inspect_deb.py',item)
    a.output.mkdir(parents=True)
    for item in artifacts:shutil.copyfile(item,a.output/item.name)
    shutil.copyfile(work/'build-record.json',a.output/'build-record.json')
    (a.output/'SHA256SUMS').write_text(''.join(hashlib.sha256(f.read_bytes()).hexdigest()+'  '+f.name+'\n' for f in sorted(a.output.iterdir())))
if __name__=='__main__':main()
