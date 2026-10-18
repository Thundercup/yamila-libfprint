#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Manage only the package's exact SELinux module; preserve administrator changes."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

POLICY_NAME='yamila_libfprint'
POLICY_PATH=Path('/usr/share/selinux/packages/yamila_libfprint.pp')


def policy_configured(root=Path('/')):
    config=Path(root)/'etc/selinux/config'
    if not config.exists():return False
    fields=dict(line.split('=',1) for line in config.read_text().splitlines() if '=' in line and not line.startswith('#'))
    if fields.get('SELINUXTYPE','').strip('"')!='targeted':raise ValueError('only targeted SELinux policy is supported')
    return True


def policy_errors(root=Path('/'), run=subprocess.run):
    # Offline fixtures have no running policy store. This does not attest SELinux.
    if Path(root)!=Path('/') or not policy_configured(root):return []
    result=run(['/usr/bin/semodule','-lfull'],capture_output=True,text=True)
    if result.returncode:return ['cannot inspect SELinux module store; run preflight with administrator privileges']
    rows=[line.split() for line in result.stdout.splitlines() if len(line.split())>=2 and line.split()[1]==POLICY_NAME]
    if not rows:return []
    if len(rows)!=1 or rows[0][0]!='200' or len(rows[0])!=3:return ['unknown priority or multiple copies of '+POLICY_NAME+' SELinux module']
    if not POLICY_PATH.is_file():return ['SELinux module already exists without package policy file']
    with tempfile.TemporaryDirectory(prefix='yamila-policy-inspect-') as tmp:
        result=run(['/usr/bin/semodule','-X','200','-H','-E',POLICY_NAME],cwd=tmp,capture_output=True,text=True)
        extracted=Path(tmp)/(POLICY_NAME+'.pp')
        if result.returncode or not extracted.is_file():return ['cannot inspect installed SELinux module source']
        if extracted.read_bytes()!=POLICY_PATH.read_bytes():return ['administrator-modified SELinux module requires explicit review']
    return []


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('install','remove','check'));a=p.parse_args()
    if a.action=='check':
        errors=policy_errors()
        if errors:sys.exit('; '.join(errors))
        return
    if os.geteuid()!=0:p.error('administrator required')
    if not policy_configured():return
    if a.action=='remove':
        errors=policy_errors()
        if errors:sys.exit('; '.join(errors))
        result=subprocess.run(['/usr/bin/semodule','-lfull'],capture_output=True,text=True,check=True)
        if not any(len(line.split())>=2 and line.split()[1]==POLICY_NAME for line in result.stdout.splitlines()):return
    command=['/usr/bin/semodule','-X','200']
    if not Path('/sys/fs/selinux/enforce').exists():command.append('-n')
    command += ['-i',str(POLICY_PATH)] if a.action=='install' else ['-r',POLICY_NAME]
    subprocess.run(command,check=True)


if __name__=='__main__':main()
