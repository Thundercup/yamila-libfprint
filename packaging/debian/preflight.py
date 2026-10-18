#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Conservative Ubuntu gate; read-only, no capture, activation or policy edits."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

PACKAGE = 'yamila-libfprint'
LIBDIR = '/usr/lib/x86_64-linux-gnu/yamila-fprint'
FILES = {
 '/usr/lib/systemd/system/fprintd.service.d/20-yamila-libfprint.conf': '[Service]\nEnvironment=LD_LIBRARY_PATH='+LIBDIR+'\nLimitCORE=0\n',
 '/usr/lib/sysusers.d/yamila-fprint.conf': 'u yamila-fprint - "Yamila isolated fingerprint worker" /var/empty /usr/sbin/nologin\n',
 '/usr/lib/udev/rules.d/70-yamila-fprint.rules': 'ACTION=="add|change", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="2808", ATTR{idProduct}=="06fc", ATTR{bcdDevice}=="2003", TAG-="uaccess", GROUP="yamila-fprint", MODE="0660"\n'
}


def query_dpkg(root, operation, value):
    if operation == 'version':
        cmd=['dpkg-query','--admindir='+str(root/'var/lib/dpkg'),'-W','-f=${Version}',value]
    elif operation == 'owner':
        cmd=['dpkg-query','--admindir='+str(root/'var/lib/dpkg'),'-S',value]
    elif operation == 'verify':
        cmd=['dpkg','--root='+str(root),'--verify',value]
    elif operation == 'status':
        cmd=['dpkg-query','--admindir='+str(root/'var/lib/dpkg'),'-W','-f=${Status}',value]
    else:raise ValueError('unknown query')
    p=subprocess.run(cmd,capture_output=True,text=True,timeout=30)
    return p.returncode,p.stdout.strip()


def inspect(baseline, root=Path('/'), query=query_dpkg):
    root=Path(root);errors=[]
    def path(name):return root/name.lstrip('/')
    def reject(message):errors.append(message)
    status_code,status=query(root,'status',PACKAGE)
    installed=status_code==0 and status.split()[-1:] == ['installed']
    try:
        release=dict(s.split('=',1) for s in path('/etc/os-release').read_text().splitlines() if '=' in s)
        if release.get('ID','').strip('"')!='ubuntu' or release.get('VERSION_ID','').strip('"')!='26.04':reject('supported OS is Ubuntu 26.04')
    except OSError:reject('cannot read OS identity')
    if os.uname().machine!='x86_64':reject('supported architecture is amd64')
    for name,version in baseline['packages'].items():
        if query(root,'version',name)!=(0,version):reject('unsupported '+name+' version; rebuild for the installed baseline')
    unit=path('/usr/lib/systemd/system/fprintd.service')
    try:
        if hashlib.sha256(unit.read_bytes()).hexdigest()!=baseline['unit_sha256']:reject('distribution fprintd unit differs from build baseline')
    except OSError:reject('missing distribution fprintd unit')
    for base in ('/etc/systemd/system','/run/systemd/system','/usr/local/lib/systemd/system'):
        p=path(base+'/fprintd.service')
        if p.exists() or p.is_symlink():reject('custom or masked fprintd unit: '+base)
        d=path(base+'/fprintd.service.d')
        if d.exists() and any(x.suffix=='.conf' for x in d.iterdir()):reject('custom fprintd drop-in: '+base)
    d=path('/usr/lib/systemd/system/fprintd.service.d')
    if d.exists():
        for item in d.iterdir():
            if item.suffix=='.conf' and '/usr/lib/systemd/system/fprintd.service.d/'+item.name not in FILES:reject('unknown vendor drop-in')
    for name,expected in FILES.items():
        p=path(name)
        if not p.exists() and not p.is_symlink():continue
        if p.is_symlink() or not p.is_file():reject('integration is not a regular file: '+name);continue
        if p.stat().st_uid!=os.geteuid() or p.stat().st_mode & 0o022:reject('unsafe integration ownership/mode: '+name)
        code,owner=query(root,'owner',name)
        if code or owner.split(': ',1)[0].split(':')[0]!=PACKAGE:reject('unowned integration: '+name)
        if not installed and p.read_text()!=expected:reject('modified retained integration: '+name)
    d=path('/etc/udev/rules.d')
    if d.exists():
        for item in d.glob('*.rules'):
            try:text=item.read_text().lower()
            except (OSError,UnicodeError):reject('unreadable local USB rule');continue
            if 'yamila' in text or ('2808' in text and '06fc' in text):reject('local Yamila USB rule needs explicit migration')
    for name in ('/usr/libexec/yamila-fprint',LIBDIR):
        d=path(name)
        if d.is_symlink():reject('symlink private runtime');continue
        if d.exists():
            for item in d.rglob('*'):
                if not item.is_file() and not item.is_symlink():continue
                code,owner=query(root,'owner','/'+str(item.relative_to(root)))
                if code or owner.split(': ',1)[0].split(':')[0]!=PACKAGE:reject('unknown private runtime file')
    if installed:
        code,detail=query(root,'verify',PACKAGE)
        if code or detail:reject('installed package modified; inspect dpkg --verify first')
    try:
        users=[x.split(':') for x in path('/etc/passwd').read_text().splitlines()]
        groups=[x.split(':') for x in path('/etc/group').read_text().splitlines()]
        own=[x for x in users if x[0]=='yamila-fprint'];group=[x for x in groups if x[0]=='yamila-fprint']
        if own:
            u=own[0]
            if len(own)!=1 or len(group)!=1 or len(u)!=7 or int(u[2])<=0 or int(u[3])<=0 or u[5:]!=['/var/empty','/usr/sbin/nologin'] or group[0][2]!=u[3] or group[0][3] or any(x[0]!='yamila-fprint' and x[3]==u[3] for x in users) or any('yamila-fprint' in x[3].split(',') for x in groups):reject('incompatible existing worker account/group')
        elif group:reject('worker group without account')
    except (OSError,ValueError,IndexError):reject('cannot validate dedicated account')
    # Do not silently weaken a separately confined daemon or enable SELinux policy.
    profiles=path('/sys/kernel/security/apparmor/profiles')
    if profiles.exists():
        try:
            if any('fprintd' in x and '(enforce)' in x for x in profiles.read_text().splitlines()):reject('enforced fprintd AppArmor profile needs explicit adaptation')
        except OSError:reject('cannot inspect fprintd AppArmor confinement')
    enforce=path('/sys/fs/selinux/enforce')
    if enforce.exists():
        try:
            if enforce.read_text().strip()=='1':reject('Ubuntu SELinux integration is not implemented')
        except OSError:reject('cannot inspect SELinux mode')
    return dict(compatible=not errors,failures=errors,changes_performed=False,biometric_data_read=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--verify-installed',action='store_true')
    args=parser.parse_args()
    if args.verify_installed:
        code,detail=query_dpkg(Path('/'),'verify',PACKAGE)
        result=dict(compatible=code==0 and not detail,failures=[] if code==0 and not detail else ['installed package modified; inspect dpkg --verify first'])
    elif args.baseline:
        result=inspect(json.loads(args.baseline.read_text()))
    else:parser.error('provide --baseline or --verify-installed')
    print(json.dumps(result,indent=2));sys.exit(0 if result['compatible'] else 2)
