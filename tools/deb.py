#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Build an experimental Ubuntu 26.04 amd64 package; never install it."""
import argparse
import gzip
import tarfile
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from audit import ROOT,audit


def run(args,**kw):return subprocess.run([str(x) for x in args],check=True,**kw)
def text(args):return subprocess.check_output(args,text=True).strip()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--upstream-archive',type=Path,required=True)
    p.add_argument('--workdir',type=Path,default=ROOT/'build/deb')
    p.add_argument('--revision',default='4')
    a=p.parse_args();audit()
    if os.geteuid()==0:p.error('build as an ordinary user')
    if text(['dpkg','--print-architecture'])!='amd64':p.error('only amd64 is supported')
    release=dict(x.split('=',1) for x in Path('/etc/os-release').read_text().splitlines() if '=' in x)
    if release.get('ID','').strip('"')!='ubuntu' or release.get('VERSION_ID','').strip('"')!='26.04':p.error('Ubuntu 26.04 build environment required')
    if not re.fullmatch('[1-9][0-9]*',a.revision) or int(a.revision)<2:p.error('automatic PAM integration requires revision 2 or later; use the frozen legacy source for revision 1')
    work=a.workdir.resolve()
    if work.exists():p.error('workdir must be new')
    work.mkdir(parents=True)
    baseline=dict(schema=1,os='ubuntu',release='26.04',architecture='amd64',packages={name:text(['dpkg-query','-W','-f=${Version}',name]) for name in ('libfprint-2-2','fprintd')},unit_sha256=hashlib.sha256(Path('/usr/lib/systemd/system/fprintd.service').read_bytes()).hexdigest())
    source=work/'source';run(['python3','-B',ROOT/'tools/export.py','--dest',source])
    archive=a.upstream_archive.resolve(strict=True);build=work/'build';stage=work/'package'
    epoch=str(json.loads((ROOT/'packaging/fedora44-build.lock.json').read_text())['source_date_epoch'])
    flags=text(['dpkg-buildflags','--get','CFLAGS'])+' -ffile-prefix-map='+str(work)+'=. -fdebug-prefix-map='+str(work)+'=.'
    env={**os.environ,'SOURCE_DATE_EPOCH':epoch,'TZ':'UTC','LC_ALL':'C.UTF-8','CFLAGS':flags,'CXXFLAGS':flags,'LDFLAGS':text(['dpkg-buildflags','--get','LDFLAGS'])}
    run(['python3','-B',ROOT/'tools/build.py','--upstream-archive',archive,'--build-dir',build,'--libdir','lib/x86_64-linux-gnu/yamila-fprint'],env=env)
    run(['python3','-B',ROOT/'tools/stage.py','--build-dir',build,'--destdir',stage],env=env)
    (stage/'stage-manifest.json').unlink()
    (stage/'usr/share/yamila-libfprint').mkdir(parents=True)
    (stage/'usr/share/yamila-libfprint/baseline.json').write_text(json.dumps(baseline,indent=2)+'\n')
    helper=ROOT/'packaging/debian/preflight.py'
    shutil.copyfile(helper,stage/'usr/libexec/yamila-fprint/ubuntu_preflight.py')
    shutil.copyfile(ROOT/'packaging/debian/pam_integration.py',stage/'usr/libexec/yamila-fprint/pam_integration.py')
    sys.path.insert(0,str(helper.parent));from preflight import FILES
    for name,content in FILES.items():
        dest=stage/name.lstrip('/');dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(content)
    version='0.0.1-'+a.revision+'ubuntu26.04'
    (work/'debian').mkdir();(work/'debian/control').write_text('Source: yamila-libfprint\nSection: admin\nPriority: optional\nMaintainer: Yamila Community Maintainers <noreply@example.invalid>\n\nPackage: yamila-libfprint\nArchitecture: amd64\nDescription: Experimental Yamila libfprint backend\n')
    elf=[stage/'usr/lib/x86_64-linux-gnu/yamila-fprint/libfprint-2.so.2.0.0',stage/'usr/libexec/yamila-fprint/native-worker',stage/'usr/libexec/yamila-fprint/engine-guard']
    for file in elf:run(['strip','--strip-unneeded',file])
    deps=subprocess.check_output(['dpkg-shlibdeps','-O',*['-e'+str(x) for x in elf]],cwd=work,text=True).strip()
    if not deps.startswith('shlibs:Depends='):raise ValueError('cannot resolve ELF dependencies')
    deps=deps.removeprefix('shlibs:Depends=')+', python3, systemd, udev, libusb-1.0-0, libpam-runtime, libpam-fprintd, fprintd, libfprint-2-2'
    control=stage/'DEBIAN';control.mkdir()
    (control/'control').write_text('Package: yamila-libfprint\nVersion: '+version+'\nArchitecture: amd64\nMaintainer: Yamila Community Maintainers <noreply@example.invalid>\nSection: admin\nPriority: optional\nPre-Depends: python3\nDepends: '+deps+'\nDescription: Experimental Yamila 2808:06fc native fprintd backend\n Includes the fixed proprietary vendor algorithm; limited user hardware feedback.\n Enables the distro fingerprint PAM profile while preserving password fallback.\n No template migration or global libfprint replacement.\n')
    code=helper.read_text().split("if __name__=='__main__':",1)[0]
    (control/'preinst').write_text("#!/bin/sh\nset -eu\ncase \"$1\" in install|upgrade) python3 -I -B - <<'YAMILA_GATE'\n"+code+'\nresult=inspect('+repr(baseline)+")\nfor warning in result['warnings']:\n print('Yamila compatibility warning: '+warning,file=sys.stderr)\nif not result['compatible']:\n print('Yamila installation refused: '+'; '.join(result['failures']),file=sys.stderr)\n sys.exit(1)\nYAMILA_GATE\n;; esac\n")
    refresh='''if [ -d /run/systemd/system ]; then
 systemctl daemon-reload
 udevadm control --reload
 udevadm trigger --action=change --subsystem-match=usb --attr-match=idVendor=2808 --attr-match=idProduct=06fc --attr-match=bcdDevice=2003
fi
'''
    (control/'postinst').write_text('''#!/bin/sh
set -eu
if [ "$1" = configure ]; then
 systemd-sysusers /usr/lib/sysusers.d/yamila-fprint.conf
 python3 -I -B -c 'import sys; sys.path.insert(0,"/usr/libexec/yamila-fprint"); from assets import check_runtime; check_runtime("/usr/libexec/yamila-fprint")' 
'''+refresh+''' if [ -d /run/systemd/system ]; then systemctl try-restart fprintd.service; fi
 python3 -I -B /usr/libexec/yamila-fprint/pam_integration.py configure
fi
case "$1" in abort-remove|abort-upgrade) python3 -I -B /usr/libexec/yamila-fprint/pam_integration.py restore ;; esac
''')
    (control/'prerm').write_text('''#!/bin/sh
set -eu
case "$1" in remove|upgrade)
 python3 -I -B /usr/libexec/yamila-fprint/ubuntu_preflight.py --verify-installed
 if [ "$1" = remove ]; then
  python3 -I -B /usr/libexec/yamila-fprint/pam_integration.py remove
  if [ -d /run/systemd/system ]; then systemctl stop fprintd.service; fi
 elif dpkg --compare-versions "$2" lt 0.0.1-2ubuntu26.04; then
  python3 -I -B /usr/libexec/yamila-fprint/pam_integration.py remove
 fi
;; esac
''')
    (control/'postrm').write_text('#!/bin/sh\nset -eu\ncase "$1" in remove|purge)\n'+refresh+'if [ -d /var/lib/yamila-libfprint ] && [ ! -L /var/lib/yamila-libfprint ]; then\n rm -f /var/lib/yamila-libfprint/pam-state.json /var/lib/yamila-libfprint/pam-state.new\n rmdir /var/lib/yamila-libfprint 2>/dev/null || :\nfi\n;; esac\n# Keep the worker account and all template data.\n')
    for name in ('preinst','postinst','prerm','postrm'):(control/name).chmod(0o755)
    md5=[]
    for file in sorted(stage.rglob('*')):
        if file.is_file() and not file.is_symlink() and 'DEBIAN' not in file.relative_to(stage).parts:
            md5.append(hashlib.md5(file.read_bytes()).hexdigest()+'  '+str(file.relative_to(stage)))
    (control/'md5sums').write_text('\n'.join(md5)+'\n')
    package=work/('yamila-libfprint_'+version+'_amd64.deb')
    run(['dpkg-deb','--root-owner-group','--build',stage,package],env=env)
    source_archive=work/('yamila-libfprint_'+version+'_source.tar.gz')
    with source_archive.open('wb') as raw:
        with gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0) as gz:
            with tarfile.open(fileobj=gz,mode='w') as tar:
                for file in sorted(source.rglob('*')):
                    if not file.is_file():continue
                    info=tar.gettarinfo(str(file),arcname='yamila-libfprint/'+str(file.relative_to(source)))
                    info.uid=info.gid=0;info.uname=info.gname='';info.mode=0o644;info.mtime=int(epoch)
                    with file.open('rb') as stream:tar.addfile(info,stream)
    # Corresponding upstream source is shipped beside the project overlay.
    upstream=json.loads((ROOT/'upstream.lock.json').read_text())
    upstream_copy=work/upstream['archive'];shutil.copyfile(archive,upstream_copy)
    record=dict(schema=1,version=version,baseline=baseline,architecture='amd64',hardware_verified=False,source_manifest_sha256=hashlib.sha256((source/'PUBLIC-MANIFEST.json').read_bytes()).hexdigest(),artifacts=[dict(file=x.name,sha256=hashlib.sha256(x.read_bytes()).hexdigest(),size=x.stat().st_size) for x in (package,source_archive,upstream_copy)])
    (work/'build-record.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))


if __name__=='__main__':main()
