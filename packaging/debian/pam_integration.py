#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Enable the distro fingerprint profile once; undo only unchanged owned state."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

STATE = '/var/lib/yamila-libfprint/pam-state.json'
STACKS = ('auth','account','password','session','session-noninteractive')


def snapshot(root):
    root=Path(root)
    configs={name:(root/'etc/pam.d'/('common-'+name)).read_bytes() for name in STACKS}
    modules={name:re.findall(r'^Module: (.+)$',(root/'var/lib/pam'/name).read_text(),re.M) for name in STACKS}
    active='\n'.join(line for line in configs['auth'].decode().splitlines() if line.strip() and not line.lstrip().startswith('#'))
    return dict(hashes={name:hashlib.sha256(data).hexdigest() for name,data in configs.items()},modules=modules,
                fingerprint=bool(re.search(r'\bpam_fprintd\.so\b',active)),unix=bool(re.search(r'\bpam_unix\.so\b',active)))


def preserves(before,after):
    # The only permitted selection change is adding/removing fprintd.
    return after['unix'] and all(before['hashes'][name]==after['hashes'][name] for name in STACKS if name!='auth') and all(set(before['modules'][name])-{'fprintd'}==set(after['modules'][name])-{'fprintd'} for name in STACKS)


def update(enabled):
    env={**os.environ,'DEBIAN_FRONTEND':'noninteractive','LC_ALL':'C.UTF-8'}
    # A previously remembered override answer must not force local PAM edits.
    answer=subprocess.run(['debconf-communicate','libpam-runtime'],input='SET libpam-runtime/override false\n',text=True,
                   stdout=subprocess.PIPE,check=True,env=env,timeout=30)
    if not answer.stdout.startswith('0 '):raise ValueError('cannot disable remembered PAM override answer')
    subprocess.run(['pam-auth-update','--package','--enable' if enabled else '--disable','fprintd'],check=True,env=env,timeout=60)


class Integration:
    def __init__(self,root=Path('/'),apply=update):
        self.root=Path(root);self.path=self.root/STATE.lstrip('/');self.apply=apply

    def load(self):
        directory=self.path.parent
        if directory.is_symlink():raise ValueError('unsafe PAM receipt directory')
        if directory.exists() and (directory.stat().st_uid!=os.geteuid() or directory.stat().st_mode & 0o077):raise ValueError('unsafe PAM receipt directory ownership/mode')
        if not self.path.exists() and not self.path.is_symlink():return None
        if self.path.is_symlink() or not self.path.is_file() or self.path.stat().st_uid!=os.geteuid() or self.path.stat().st_mode & 0o077:raise ValueError('unsafe PAM receipt')
        state=json.loads(self.path.read_text())
        if state.get('schema')!=1 or state.get('phase') not in ('pending','owned','preserved','released','blocked'):raise ValueError('invalid PAM receipt')
        return state

    def save(self,state):
        self.path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        temp=self.path.with_suffix('.new')
        # Never follow a stale or injected temporary-file link.
        if temp.exists() or temp.is_symlink():
            if temp.is_symlink() or not temp.is_file() or temp.stat().st_uid!=os.geteuid() or temp.stat().st_mode & 0o077:raise ValueError('unsafe pending PAM receipt')
            temp.unlink()
        fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try:
            with os.fdopen(fd,'w') as stream:
                json.dump(state,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
            temp.replace(self.path)
        finally:temp.unlink(missing_ok=True)

    def configure(self):
        state=self.load();now=snapshot(self.root)
        if state and state['phase'] in ('owned','preserved'):
            # Reconfiguration/upgrades respect subsequent administrator choices.
            return {'action':'preserved-current-choice','fingerprint_enabled':now['fingerprint']}
        if state and state['phase']=='pending':
            if now['fingerprint'] and preserves(state['before'],now):
                state.update(phase='owned',after=now);self.save(state)
                return {'action':'recovered-completed-enable','fingerprint_enabled':True}
            if now!=state['before']:raise ValueError('PAM changed during interrupted enable; inspect before retrying')
        else:
            state=dict(schema=1,phase='pending',before=now)
        if now['fingerprint']:
            state.update(phase='preserved');self.save(state)
            return {'action':'kept-preexisting-fingerprint','fingerprint_enabled':True}
        if not now['unix'] or 'unix' not in now['modules']['auth']:
            raise ValueError('managed Unix password fallback required for automatic fingerprint enable')
        if 'fprintd' in now['modules']['auth']:
            raise ValueError('fingerprint selection and effective PAM stack disagree')
        self.save(state)
        try:
            self.apply(True);after=snapshot(self.root)
        except Exception:
            # The pending receipt permits conservative retry/removal after interruption.
            raise
        if not after['fingerprint'] or 'fprintd' not in after['modules']['auth'] or not preserves(now,after):
            state.update(phase='blocked');self.save(state)
            raise ValueError('PAM profile was not safely enabled; local edits were not forced; inspect pam-auth-update output')
        state.update(phase='owned',after=after);self.save(state)
        return {'action':'enabled-distro-fprintd','fingerprint_enabled':True}

    def remove(self):
        state=self.load()
        if not state:return {'action':'no-owned-PAM-change'}
        now=snapshot(self.root)
        if state['phase']=='pending' and now['fingerprint'] and preserves(state['before'],now):
            # Recover a command completed before receipt commit.
            state.update(phase='owned',after=now);self.save(state)
        if state['phase']!='owned':return {'action':'kept-preexisting-or-unowned-PAM'}
        if not now['fingerprint']:
            state.update(phase='released',restore_on_abort=False);self.save(state)
            return {'action':'kept-administrator-disabled-choice'}
        if now!=state['after']:
            return {'action':'kept-administrator-modified-PAM','notice':'Fingerprint preference retained; use pam-auth-update --disable fprintd explicitly if desired.'}
        self.apply(False);after=snapshot(self.root)
        if after['fingerprint'] or 'fprintd' in after['modules']['auth'] or not preserves(state['before'],after):
            raise ValueError('PAM rollback was not applied safely; package removal stopped')
        state.update(phase='released',released=after,restore_on_abort=True);self.save(state)
        return {'action':'restored-original-disabled-fingerprint','fingerprint_enabled':False}

    def restore(self):
        state=self.load()
        if not state or state['phase']!='released' or not state.get('restore_on_abort'):return {'action':'nothing-to-restore'}
        now=snapshot(self.root)
        if now!=state['released']:raise ValueError('PAM changed after attempted removal; automatic restore refused')
        self.apply(True);after=snapshot(self.root)
        if not after['fingerprint'] or not preserves(state['before'],after):raise ValueError('PAM restoration failed')
        state.update(phase='owned',after=after);self.save(state)
        return {'action':'restored-after-aborted-removal','fingerprint_enabled':True}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['configure','remove','restore']);a=p.parse_args()
    if os.geteuid()!=0:p.error('package integration must run as root')
    if a.action=='configure':
        verified=subprocess.run(['dpkg','--verify','libpam-fprintd'],capture_output=True,text=True,timeout=30)
        changes=[]
        for line in verified.stdout.splitlines():
            name=line.rsplit(None,1)[-1]
            # Minimal container images may intentionally omit documentation.
            if line.startswith('missing ') and name.startswith(('/usr/share/doc/libpam-fprintd/','/usr/share/man/')):continue
            changes.append(line)
        if verified.returncode or changes:raise ValueError('distribution fingerprint PAM package modified or unavailable')
        for name in ('/usr/share/pam-configs/fprintd','/usr/lib/x86_64-linux-gnu/security/pam_fprintd.so'):
            path=Path(name)
            if path.is_symlink() or not path.is_file() or path.stat().st_uid!=0 or path.stat().st_mode & 0o022:
                raise ValueError('unsafe distribution PAM module/profile')
    print(json.dumps(getattr(Integration(),a.action)(),indent=2))

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,subprocess.SubprocessError) as error:sys.exit('Yamila PAM integration refused: '+str(error))
