#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Read-only installation gate; no service activation, USB or biometric reads."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from selinux_policy import policy_errors, POLICY_PATH

PACKAGE = 'yamila-libfprint'
VERSIONS = {'libfprint':'1.94.100-1.fc44', 'fprintd':'1.94.5-5.fc44', 'selinux-policy-targeted':'44.11-1.fc44'}
FILES = {
 '/usr/lib/systemd/system/fprintd.service.d/20-yamila-libfprint.conf': '[Service]\nEnvironment=LD_LIBRARY_PATH=/usr/lib64/yamila-fprint\nLimitCORE=0\n',
 '/usr/lib/sysusers.d/yamila-fprint.conf': 'u yamila-fprint - "Yamila isolated fingerprint worker" /var/empty /usr/sbin/nologin\n',
 '/usr/lib/udev/rules.d/70-yamila-fprint.rules': 'ACTION=="add|change", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="2808", ATTR{idProduct}=="06fc", ATTR{bcdDevice}=="2003", TAG-="uaccess", GROUP="yamila-fprint", MODE="0660"\n'
}


def query_rpm(root, *args):
    result = subprocess.run(['/usr/bin/rpm','--root',str(root),*args],capture_output=True,text=True)
    return result.returncode, result.stdout.strip()


def inspect(root=Path('/'), query=query_rpm):
    root = Path(root)
    failures=[]
    installed=query(root,'-q',PACKAGE)[0]==0
    def path(name):return root/name.lstrip('/')
    def reject(message):failures.append(message)
    os_release=path('/etc/os-release')
    try:
        release=dict(line.split('=',1) for line in os_release.read_text().splitlines() if '=' in line)
        if release.get('ID','').strip('"')!='fedora' or release.get('VERSION_ID','').strip('"')!='44':reject('supported OS is Fedora 44')
    except OSError:reject('cannot read OS identity')
    if os.uname().machine!='x86_64':reject('supported architecture is x86_64')
    for name,version in VERSIONS.items():
        code,value=query(root,'-q','--queryformat',chr(37)+'{VERSION}-'+chr(37)+'{RELEASE}',name)
        if code or value!=version:reject('unsupported '+name+' version; expected '+version)
    for base in ('/etc/systemd/system','/run/systemd/system','/usr/local/lib/systemd/system'):
        unit=path(base+'/fprintd.service')
        if unit.exists() or unit.is_symlink():reject('custom or masked fprintd unit: '+base+'/fprintd.service')
        folder=path(base+'/fprintd.service.d')
        if folder.exists():
            for item in sorted(folder.iterdir()):
                if item.suffix=='.conf':reject('unknown fprintd drop-in: '+base+'/fprintd.service.d/'+item.name)
    vendor_dropins=path('/usr/lib/systemd/system/fprintd.service.d')
    if vendor_dropins.exists():
        for item in sorted(vendor_dropins.iterdir()):
            name='/usr/lib/systemd/system/fprintd.service.d/'+item.name
            if item.suffix=='.conf' and name not in FILES:reject('unknown vendor fprintd drop-in: '+name)
    for name,expected in FILES.items():
        item=path(name)
        if not item.exists() and not item.is_symlink():continue
        if item.is_symlink() or not item.is_file():reject('managed integration path is not a regular file: '+name);continue
        if item.stat().st_uid!=os.geteuid() or item.stat().st_mode & 0o022:reject('untrusted integration ownership/mode: '+name)
        if item.read_text()!=expected and not installed:reject('modified integration file: '+name)
        # An installed older config may legitimately differ from the new RPM.
        # rpm -V below authenticates it against its own installed manifest.
        code,owner=query(root,'-qf','--queryformat',chr(37)+'{NAME}',name)
        if code or owner!=PACKAGE:reject('integration file not owned by '+PACKAGE+': '+name)
    rules=path('/etc/udev/rules.d')
    if rules.exists():
        for item in sorted(rules.iterdir()):
            if item.suffix!='.rules':continue
            try:text=item.read_text().lower()
            except (OSError,UnicodeError):reject('unreadable local USB rule: '+item.name);continue
            if 'yamila' in text or ('2808' in text and '06fc' in text):reject('local Yamila USB rule requires explicit migration: /etc/udev/rules.d/'+item.name)
    for directory in ('/usr/libexec/yamila-fprint','/usr/lib64/yamila-fprint'):
        base=path(directory)
        if base.is_symlink():reject('private runtime directory is a symlink: '+directory);continue
        if base.exists():
            for item in base.rglob('*'):
                if not item.is_file() and not item.is_symlink():continue
                name='/'+str(item.relative_to(root))
                code,owner=query(root,'-qf','--queryformat',chr(37)+'{NAME}',name)
                if code or owner!=PACKAGE:reject('unknown file in private runtime: '+name)
    code,_=query(root,'-q',PACKAGE)
    if code==0:
        code,detail=query(root,'-V',PACKAGE)
        if code or detail:reject('installed '+PACKAGE+' verification failed; inspect rpm -V before upgrade')
    # A dedicated, locked-login service identity may persist after uninstall.
    passwd=path('/etc/passwd')
    group=path('/etc/group')
    if passwd.exists():
        entries=[line.split(':') for line in passwd.read_text().splitlines() if line.startswith('yamila-fprint:')]
        groups=[line.split(':') for line in group.read_text().splitlines() if line.startswith('yamila-fprint:')] if group.exists() else []
        if len(entries)>1:reject('duplicate yamila-fprint account')
        if entries:
            row=entries[0]
            try:
                if len(row)!=7 or int(row[2])<=0 or int(row[3])<=0 or row[5]!='/var/empty' or row[6]!='/usr/sbin/nologin':raise ValueError()
                if len(groups)!=1 or groups[0][2]!=row[3] or groups[0][3]:raise ValueError()
            except (ValueError,IndexError):reject('existing yamila-fprint account/group is incompatible')
        elif groups:reject('pre-existing yamila-fprint group without account')
    policy_file=path(str(POLICY_PATH))
    if policy_file.exists() or policy_file.is_symlink():
        code,owner=query(root,'-qf','--queryformat',chr(37)+'{NAME}',str(POLICY_PATH))
        if policy_file.is_symlink() or code or owner!=PACKAGE:reject('unknown SELinux package policy file')
    failures.extend(policy_errors(root))
    return dict(compatible=not failures, failures=failures, expected_versions=VERSIONS,
                changes_performed=False, biometric_data_read=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('/'),help='read-only filesystem/RPM root')
    args=parser.parse_args()
    result=inspect(args.root.resolve())
    print(json.dumps(result,indent=2))
    return 0 if result['compatible'] else 2


if __name__=='__main__':sys.exit(main())
