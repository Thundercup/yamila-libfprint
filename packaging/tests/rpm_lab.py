#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""User-namespace RPM transaction lab with own scriptlets, never host install.

Seeds minimal binaries and a SQLite backup of host package metadata. This is
not a clean Fedora image; distribution triggers and SELinux are not exercised.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time


def copy_binary(root,path):
    path=Path(path)
    if not path.exists():return
    dst=root/str(path).lstrip('/');dst.parent.mkdir(parents=True,exist_ok=True)
    if not dst.exists():shutil.copy2(path.resolve(),dst)
    result=subprocess.run(['ldd',str(path)],capture_output=True,text=True,check=True)
    for name in re.findall(r'(?:=>\s+|^\s*)(/[^\s]+)',result.stdout,re.M):
        p=Path(name);target=root/name.lstrip('/');target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():shutil.copy2(p.resolve(),target)


def prepare(root):
    root.mkdir()
    for name in ('usr/lib64','usr/bin','usr/sbin','usr/libexec','etc','run','tmp','var/tmp','var/lib/fprint','usr/lib/sysimage/rpm'):(root/name).mkdir(parents=True,exist_ok=True)
    for name,target in [('lib64','usr/lib64'),('lib','usr/lib'),('bin','usr/bin'),('sbin','usr/sbin')]: (root/name).symlink_to(target)
    for binary in ('/usr/bin/python3','/usr/bin/sh','/usr/bin/rpm','/usr/bin/systemd-sysusers','/usr/libexec/fprintd','/usr/bin/dbus-daemon','/usr/bin/gdbus'):
        copy_binary(root,binary)
    shutil.copytree('/usr/lib/rpm',root/'usr/lib/rpm',dirs_exist_ok=True)
    (root/'etc/os-release').write_text('ID=fedora\nVERSION_ID=44\n')
    (root/'etc/passwd').write_text('root:x:0:0:root:/root:/bin/sh\n')
    (root/'etc/group').write_text('root:x:0:\n')
    (root/'etc/shadow').write_text('root:!*:1::::::\n')
    (root/'etc/gshadow').write_text('root:!::\n')
    (root/'etc/nsswitch.conf').write_text('passwd: files\ngroup: files\nshadow: files\n')
    (root/'var/lib/fprint/synthetic-preserve').write_bytes(b'SYNTHETIC-FPRINT-NO-BIOMETRICS')
    (root/'var/lib/fprint/synthetic-preserve').chmod(0o600)
    source=sqlite3.connect('file:/usr/lib/sysimage/rpm/rpmdb.sqlite?mode=ro',uri=True)
    target=sqlite3.connect(root/'usr/lib/sysimage/rpm/rpmdb.sqlite')
    source.backup(target);target.close();source.close()


def inside(package1,package2):
    assert os.geteuid()==0
    assert Path('/run/yamila-rpm-lab').read_text()=='isolated-rpm-lab-v1'
    # No real devices, system bus or running systemd are exposed.
    assert not Path('/run/systemd/system').exists()
    results=[]
    def rpm(*args,ok=True):
        options=['--notriggers'] if args[0] in ('-i','-U','-e') else []
        p=subprocess.run(['/usr/bin/rpm','--root','/lab','--noplugins',*options,*args],capture_output=True,text=True)
        if ok and p.returncode:raise AssertionError(p.stdout+p.stderr)
        if not ok and p.returncode==0:raise AssertionError('transaction unexpectedly succeeded')
        if p.stderr:print(p.stderr,flush=True)
        return p
    def check_data():
        assert Path('/lab/var/lib/fprint/synthetic-preserve').read_bytes()==b'SYNTHETIC-FPRINT-NO-BIOMETRICS'
    original=hashlib.sha256(Path('/lab/usr/lib64/libfprint-2.so.2').read_bytes()).hexdigest()
    old=Path('/lab/etc/systemd/system/fprintd.service.d/90-old-gateway.conf')
    old.parent.mkdir(parents=True);old.write_text('[Service]\nExecStart=/synthetic-old-gateway\n')
    p=rpm('-i',package1,ok=False);assert 'installation refused' in p.stderr
    assert old.read_text().endswith('/synthetic-old-gateway\n')
    assert not Path('/lab/usr/libexec/yamila-fprint').exists();check_data();old.unlink()
    assert 'yamila-fprint:' not in Path('/lab/etc/passwd').read_text()
    results.append('old gateway preinstall rejected without payload changes')
    rpm('-i',package1)
    account=[x for x in Path('/lab/etc/passwd').read_text().splitlines() if x.startswith('yamila-fprint:')]
    assert len(account)==1 and int(account[0].split(':')[2])>0 and account[0].endswith('/usr/sbin/nologin')
    assert not rpm('-V','yamila-libfprint').stdout.strip()
    check_data();results.append('install with actual pre/post scriptlets and dynamic system account')
    config=Path('/lab/usr/lib/systemd/system/fprintd.service.d/20-yamila-libfprint.conf')
    expected=config.read_text();before=config.stat();config.write_text(expected+'# modified locally\n')
    rpm('-U',package2,ok=False)
    assert rpm('-q','--qf','%{RELEASE}','yamila-libfprint').stdout=='1.fc44'
    assert config.read_text().endswith('# modified locally\n');check_data()
    config.write_text(expected);os.utime(config,ns=(before.st_atime_ns,before.st_mtime_ns));results.append('modified configuration rejects upgrade and keeps old package/data')
    rpm('-U',package2);assert rpm('-q','--qf','%{RELEASE}','yamila-libfprint').stdout=='2.fc44'
    results.append('upgrade transaction')
    rpm('-U','--oldpackage',package1);assert rpm('-q','--qf','%{RELEASE}','yamila-libfprint').stdout=='1.fc44'
    results.append('downgrade rollback transaction')
    rpm('-e','yamila-libfprint');check_data()
    assert not config.exists() and not Path('/lab/usr/libexec/yamila-fprint/broker.py').exists()
    assert 'yamila-fprint:' in Path('/lab/etc/passwd').read_text()
    assert hashlib.sha256(Path('/lab/usr/lib64/libfprint-2.so.2').read_bytes()).hexdigest()==original
    results.append('uninstall preserves FpPrint fixture, account and original library')
    rpm('-i',package1);assert not rpm('-V','yamila-libfprint').stdout.strip()
    rpm('-e','yamila-libfprint');check_data();results.append('reinstall after retained account and data')
    print(json.dumps(dict(checks=results,scope='own RPM scriptlets; seeded package metadata; no distro triggers/SELinux/service activation'),indent=2))


def main():
    if len(sys.argv)>1 and sys.argv[1]=='--inside':
        inside(sys.argv[2],sys.argv[3]);return
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rpm1',type=Path,required=True)
    parser.add_argument('--rpm2',type=Path,required=True)
    parser.add_argument('--workdir',type=Path,required=True)
    args=parser.parse_args()
    work=args.workdir.resolve()
    if work.exists():parser.error('--workdir must be new')
    work.mkdir();root=work/'root';prepare(root)
    # All metadata, files and markers are confined to this disposable lab.
    (work/'marker').write_text('isolated-rpm-lab-v1')
    shutil.copyfile(args.rpm1,work/'one.rpm');shutil.copyfile(args.rpm2,work/'two.rpm')
    stdlib='/usr/lib64/python'+str(sys.version_info.major)+'.'+str(sys.version_info.minor)
    (root/stdlib.lstrip('/')).mkdir(parents=True)
    cmd=['bwrap','--unshare-user','--unshare-pid','--unshare-ipc','--unshare-uts','--uid','0','--gid','0','--cap-add','CAP_SYS_CHROOT','--die-with-parent',
      '--ro-bind','/usr','/usr','--symlink','usr/lib64','/lib64','--symlink','usr/lib','/lib','--symlink','usr/bin','/bin','--symlink','usr/sbin','/sbin',
      '--proc','/proc','--dev','/dev','--tmpfs','/tmp','--tmpfs','/run','--tmpfs','/etc',
      '--bind',str(root),'/lab','--ro-bind',stdlib,'/lab'+stdlib,
      '--ro-bind',str(work/'one.rpm'),'/one.rpm','--ro-bind',str(work/'two.rpm'),'/two.rpm',
      '--ro-bind',str(work/'marker'),'/run/yamila-rpm-lab','--ro-bind',str(Path(__file__).resolve()),'/lab-test.py',
      '--setenv','PYTHONDONTWRITEBYTECODE','1','--setenv','HOME','/tmp','--setenv','LC_ALL','C',
      '--','/usr/bin/python3','-I','-B','/lab-test.py','--inside','/one.rpm','/two.rpm']
    subprocess.run(cmd,check=True)


if __name__=='__main__':main()
