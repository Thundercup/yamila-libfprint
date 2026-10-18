#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Inspect a DEB without installing, starting services or executing its DLL."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile
from audit import ROOT
from privacy_check import scan
sys.path.insert(0,str(ROOT/'runtime'))
from assets import DLL_SHA

LIB='usr/lib/x86_64-linux-gnu/yamila-fprint/'
RUNTIME='usr/libexec/yamila-fprint/'

def inspect(package,denied=()):
    control=subprocess.check_output(['dpkg-deb','-f',str(package)],text=True)
    if 'Architecture: amd64' not in control or 'Package: yamila-libfprint\n' not in control:raise ValueError('unexpected package identity')
    data=subprocess.check_output(['dpkg-deb','--fsys-tarfile',str(package)])
    allowed_dirs=('usr/lib/x86_64-linux-gnu/yamila-fprint/','usr/libexec/yamila-fprint/','usr/share/doc/yamila-libfprint/','usr/share/yamila-libfprint/')
    integration={'usr/lib/systemd/system/fprintd.service.d/20-yamila-libfprint.conf','usr/lib/sysusers.d/yamila-fprint.conf','usr/lib/udev/rules.d/70-yamila-fprint.rules'}
    files={};links={}
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for member in tar.getmembers():
            name=member.name.removeprefix('./');p=PurePosixPath(name)
            if p.is_absolute() or '..' in p.parts:raise ValueError('archive escape')
            if member.uid or member.gid or (not member.issym() and member.mode & 0o6022):raise ValueError('unsafe ownership/mode')
            if member.isdir():continue
            if name in files or name in links:raise ValueError('duplicate payload')
            if member.issym():
                expected={LIB+'libfprint-2.so':'libfprint-2.so.2',LIB+'libfprint-2.so.2':'libfprint-2.so.2.0.0'}
                if expected.get(name)!=member.linkname:raise ValueError('unexpected symlink')
                links[name]=member.linkname;continue
            if not member.isfile():raise ValueError('unexpected file type')
            if name not in integration and not name.startswith(allowed_dirs):raise ValueError('unexpected payload path: '+name)
            files[name]=tar.extractfile(member).read()
    if hashlib.sha256(files[RUNTIME+'vendor/YmlWbioEngineAdapter.dll']).hexdigest()!=DLL_SHA:raise ValueError('DLL identity mismatch')
    if set(links)!={LIB+'libfprint-2.so',LIB+'libfprint-2.so.2'} or not integration<=files.keys():raise ValueError('missing integration')
    if scan(control,denied):raise ValueError('private marker in control')
    for name,data in files.items():
        if name==RUNTIME+'vendor/YmlWbioEngineAdapter.dll':continue
        if scan(data.decode('utf-8',errors='replace'),denied):raise ValueError('private marker in payload: '+name)
    with tempfile.TemporaryDirectory() as temp:
        temp=Path(temp)
        subprocess.run(['dpkg-deb','-e',str(package),str(temp/'control')],check=True)
        for name in ('preinst','postinst','prerm','postrm'):
            script=temp/'control'/name
            subprocess.run(['sh','-n',str(script)],check=True)
            if scan(script.read_text(),denied):raise ValueError('private marker in maintainer script')
        for name in (LIB+'libfprint-2.so.2.0.0',RUNTIME+'native-worker',RUNTIME+'engine-guard'):
            target=temp/Path(name).name;target.write_bytes(files[name])
            dynamic=subprocess.check_output(['readelf','-d',str(target)],text=True)
            if '(RPATH)' in dynamic or '(RUNPATH)' in dynamic:raise ValueError('build path in ELF')
    return dict(package=package.name,sha256=hashlib.sha256(package.read_bytes()).hexdigest(),files=len(files),links=len(links),hardware_verified=False)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('package',type=Path);p.add_argument('--deny-text',action='append',default=[]);a=p.parse_args()
    print(json.dumps(inspect(a.package,a.deny_text),indent=2))
if __name__=='__main__':main()
