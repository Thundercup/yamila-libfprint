#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Build source and binary RPMs from audited sources and pinned upstream input."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
from audit import ROOT,audit


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream-archive',type=Path,required=True)
    parser.add_argument('--workdir',type=Path,default=ROOT/'build/rpm')
    parser.add_argument('--release',default='10')
    parser.add_argument('--local-headers',type=Path,help='explicit local development pkg-config directory')
    parser.add_argument('--allow-missing-build-deps',action='store_true',help='development-only: mark rpmbuild --nodeps; not a clean build')
    parser.add_argument('--container-build',action='store_true',help='ordinary-user build in an already isolated container, at /tmp/yamila-rpmbuild only')
    args=parser.parse_args()
    if not re.fullmatch('[1-9][0-9]*',args.release):parser.error('release must be a positive integer')
    if args.allow_missing_build_deps and not args.local_headers:parser.error('the development override requires explicit --local-headers')
    manifest=audit()
    upstream=json.loads((ROOT/'upstream.lock.json').read_text())
    archive=args.upstream_archive.resolve(strict=True)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=upstream['sha256']:raise ValueError('upstream SHA-256 mismatch')
    work=args.workdir.resolve()
    if args.container_build and (os.geteuid()==0 or work!=Path('/tmp/yamila-rpmbuild')):
        parser.error('--container-build requires an ordinary user and /tmp/yamila-rpmbuild')
    if work.exists():parser.error('--workdir must be new')
    for name in ('SOURCES','SPECS','BUILD','BUILDROOT','RPMS','SRPMS','tmp'):(work/name).mkdir(parents=True,exist_ok=True)
    lock=json.loads((ROOT/'packaging/fedora44-build.lock.json').read_text())
    epoch=lock['source_date_epoch']
    source=work/'SOURCES/yamila-libfprint-0.0.1.tar.gz'
    with source.open('wb') as raw:
        with gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0) as gz:
            with tarfile.open(fileobj=gz,mode='w') as tar:
                for name in sorted([i['path'] for i in manifest['files']]+['PUBLIC-MANIFEST.json']):
                    p=ROOT/name;info=tar.gettarinfo(str(p),arcname='yamila-libfprint-0.0.1/'+name)
                    info.uid=info.gid=0;info.uname=info.gname='';info.mode=0o644;info.mtime=epoch
                    with p.open('rb') as f:tar.addfile(info,f)
    shutil.copyfile(archive,work/'SOURCES'/upstream['archive'])
    preflight=(ROOT/'packaging/preflight.py').read_text().split("if __name__=='__main__':",1)[0]
    policy=(ROOT/'packaging/selinux_policy.py').read_text().split("if __name__=='__main__':",1)[0]
    preflight=preflight.replace('from selinux_policy import policy_errors, POLICY_PATH',policy)
    spec=(ROOT/'packaging/yamila-libfprint.spec.in').read_text().replace('@@RELEASE@@',args.release).replace('@@PREFLIGHT@@',preflight)
    requirements='\n'.join('BuildRequires: '+name+' = '+version for name,version in lock['build_requires'].items())
    spec=spec.replace('@@BUILD_REQUIRES@@',requirements)
    specpath=work/'SPECS/yamila-libfprint.spec';specpath.write_text(spec)
    env={**os.environ,'SOURCE_DATE_EPOCH':str(epoch),'TZ':'UTC','LC_ALL':'C.UTF-8'}
    if args.local_headers:env['PKG_CONFIG_PATH']=str(args.local_headers.resolve())
    # RPM 6 records expanded spec text, including its build paths, in SRPM.
    # A fixed mount path makes both that header and binary Sourcesigmd5 stable.
    fixed='/tmp/yamila-rpmbuild'
    cmd=['rpmbuild','-ba','--define','_topdir '+fixed,'--define','_tmppath '+fixed+'/tmp','--define','_buildhost yamila-builder','--define','dist .fc44']
    if args.allow_missing_build_deps:cmd.append('--nodeps')
    cmd.append(fixed+'/SPECS/yamila-libfprint.spec')
    sandbox=['bwrap','--unshare-user','--unshare-pid','--unshare-ipc','--unshare-uts','--die-with-parent',
             '--ro-bind','/','/','--tmpfs','/tmp','--tmpfs','/run','--proc','/proc','--dev','/dev',
             '--bind',str(work),fixed,'--chdir',fixed,'--setenv','HOME','/tmp']
    if args.local_headers:
        # .pc metadata may have absolute prefixes; expose inputs read-only.
        # The supported local layout is PREFIX/lib64/pkgconfig plus include.
        headers=args.local_headers.resolve().parents[1]
        sandbox.extend(['--ro-bind',str(headers),str(headers)])
    subprocess.run(cmd if args.container_build else [*sandbox,'--',*cmd],check=True,env=env)
    records=[]
    for package in sorted([*(work/'RPMS').rglob('*.rpm'),*(work/'SRPMS').rglob('*.rpm')]):
        records.append(dict(file=str(package.relative_to(work)),sha256=hashlib.sha256(package.read_bytes()).hexdigest(),size=package.stat().st_size))
    (work/'build-record.json').write_text(json.dumps(dict(schema=1,artifacts=records,source_date_epoch=epoch,
       development_dependency_override=args.allow_missing_build_deps,container_build=args.container_build,fixed_build_path=fixed,clean_environment=False,upstream_sha256=upstream['sha256'],source_sha256=hashlib.sha256(source.read_bytes()).hexdigest()),indent=2)+'\n')
    print(json.dumps(records,indent=2))


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,subprocess.CalledProcessError) as error:sys.exit(str(error))
