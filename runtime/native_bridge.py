# SPDX-License-Identifier: LGPL-2.1-or-later
"""The established bounded IPC, backed by a Linux ELF worker instead of Wine."""
import contextlib
import fcntl
import os
from pathlib import Path
import selectors
import subprocess

HERE=Path(__file__).resolve().parent
from bridge import EngineWorker,BridgeError,DLL_SHA
from assets import validate_dll
DLL=HERE/'vendor/YmlWbioEngineAdapter.dll'
WORKER=HERE/'engine-guard'



class NativeEngineWorker(EngineWorker):
    def __init__(self,emit=lambda **event:None,new_session=True,lock_path=None,stderr_path=None):
        super().__init__(emit,new_session,lock_path or HERE/'.worker.lock',startup_timeout=10,stderr_path=stderr_path)
        if lock_path is None: raise ValueError("private worker lock_path required")
        self.native_audit=None

    def __enter__(self):
        try:
            validate_dll(DLL)
            with WORKER.open('rb') as file:
                if file.read(4)!=b'\x7fELF':raise BridgeError('native worker must be a Linux ELF executable')
            self.lock=self.lock_path.open('a');fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with (self.stderr_path.open('xb') if self.stderr_path else contextlib.nullcontext(subprocess.DEVNULL)) as stderr:
                self.process=subprocess.Popen([str(WORKER),str(DLL)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                              stderr=stderr,start_new_session=self.new_session)
            os.set_blocking(self.process.stdin.fileno(),False)
            self.selector=selectors.DefaultSelector();self.selector.register(self.process.stdout,selectors.EVENT_READ)
            ready=self.until('ready',10)
            if ready.get('runtime')!='linux-pe' or ready.get('ipc_version')!=1:raise BridgeError('native worker handshake mismatch')
            return self
        except BaseException:self.close(force=True);raise

    def read_event(self,deadline):
        event=super().read_event(deadline)
        if event.get('event')=='native_audit':
            if event.get('imports_resolved')!=107 or event.get('unsupported_calls')!=0:
                raise BridgeError('native compatibility audit failed')
            self.native_audit=event
        if event.get('event')=='closed' and (event.get('runtime')!='linux-pe' or self.native_audit is None):
            raise BridgeError('native worker did not provide its final audit')
        return event
