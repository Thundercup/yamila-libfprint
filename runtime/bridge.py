# SPDX-License-Identifier: LGPL-2.1-or-later
"""Bounded engine IPC and sample/record format validation."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import select
import signal
import struct
import subprocess
import time

from protocol import image_words

DLL_SHA='f745baf9c94488473e98472a5e779c120abfa72a2058af3b9c61c80affc7a9c1'
FORMAT='gray8-shift2-64x80-v1'
MAX_LINE=7*1024*1024
BIR_HEADER=bytes.fromhex('3000000020000000381400005000000000000000000000000000000000000000c00711112800000008000000000100000000000000000000000000000000000000000000000000001b00010400000000381400000000000000524946003031300000000000000000000000000000000001010800000000001014000040005000000101fe00000000')


class BridgeError(Exception):
    pass


def bir_from_raw(raw,purpose):
    if purpose not in (1,4):raise ValueError('invalid BIR purpose')
    words=image_words(raw)
    header=bytearray(BIR_HEADER)
    if len(header)!=136:raise BridgeError('invalid BIR header constant')
    header[45]=purpose
    return bytes(header)+bytes(word>>2 for word in words)


def validate_record(record):
    if not isinstance(record,dict) or set(record)!={'template_hex','index_hex','payload_hex'}:
        raise BridgeError('invalid record schema')
    parts=[]
    for key,maximum in [('template_hex',2*1024*1024),('index_hex',4096*4),('payload_hex',1024*1024)]:
        value=record[key]
        if not isinstance(value,str) or len(value)>maximum*2 or len(value)%2 or not re.fullmatch('[0-9a-f]*',value):
            raise BridgeError('invalid or oversized record field')
        parts.append(bytes.fromhex(value))
    template,index,payload=parts
    if not template or len(index)%4:raise BridgeError('invalid record lengths')
    return struct.pack('<III',len(template),len(index)//4,len(payload))+template+index+payload


class EngineWorker:
    def __init__(self,emit=lambda **event:None,new_session=True,lock_path=None,startup_timeout=25,stderr_path=None):
        self.new_session=new_session
        self.startup_timeout=startup_timeout
        self.stderr_path=Path(stderr_path) if stderr_path else None
        self.lock_path=Path(lock_path) if lock_path else Path(__file__).parent/'.worker.lock'
        self.emit=emit;self.process=None;self.buffer=bytearray();self.lock=None;self.selector=None

    def read_event(self,deadline):
        while b'\n' not in self.buffer:
            remaining=deadline-time.monotonic()
            if remaining<=0 or not self.selector.select(remaining):raise BridgeError('engine response timed out')
            chunk=os.read(self.process.stdout.fileno(),65536)
            if not chunk:raise BridgeError(f'engine exited before response: {self.process.poll()}')
            self.buffer.extend(chunk)
            if len(self.buffer)>MAX_LINE:raise BridgeError('engine response exceeds bound')
        line,_,rest=self.buffer.partition(b'\n');self.buffer=bytearray(rest)
        event=json.loads(line)
        if not isinstance(event,dict):raise BridgeError('engine response is not an object')
        # Never log record bodies or fingerprint samples.
        self.emit(**{k:v for k,v in event.items() if k!='record'})
        return event

    def until(self,event_type,timeout,op=None):
        deadline=time.monotonic()+timeout
        while True:
            event=self.read_event(deadline)
            if event.get('event')=='exception':raise BridgeError('vendor engine exception')
            if event.get('event')==event_type:
                if op is not None and event.get('op')!=op:raise BridgeError('IPC operation mismatch')
                return event

    def request(self,op,data=b''):
        if len(data)>12+2*1024*1024+4096*4+1024*1024:raise BridgeError('IPC input too large')
        packet=memoryview(struct.pack('<BI',op,len(data))+data)
        deadline=time.monotonic()+15;fd=self.process.stdin.fileno()
        while packet:
            remaining=deadline-time.monotonic()
            if remaining<=0 or not select.select([],[fd],[],remaining)[1]:
                raise BridgeError('engine input timed out')
            try:sent=os.write(fd,packet[:65536])
            except BlockingIOError:continue
            if not sent:raise BridgeError('engine input closed')
            packet=packet[sent:]
        return self.until('result',15,op)

    def begin(self):return self.require(self.request(1))
    def enroll(self,raw):return self.request(2,bir_from_raw(raw,4))
    def commit(self):
        result=self.require(self.request(6));record=result.get('record');validate_record(record);return record
    def load(self,record):return self.require(self.request(4,validate_record(record)))
    def verify(self,raw):return self.request(3,bir_from_raw(raw,1))

    @staticmethod
    def require(result):
        if result.get('hresult')!='0x00000000':raise BridgeError('engine failure: '+str(result.get('hresult')))
        return result

    def close(self,force=False):
        error=None
        if self.process:
            if not force and self.process.poll() is not None:
                error=BridgeError('engine exited unexpectedly before cleanup')
            if not force and self.process.poll() is None:
                try:
                    self.require(self.request(5));closed=self.until('closed',5)
                    code=self.process.wait(timeout=5)
                    shim=closed['shim']
                    if code!=0 or shim['device_io_control']!={'calls':1,'allowed':1,'denied':0} or shim['create_file_w_calls'] or shim['create_directory_w_calls']:
                        raise BridgeError('engine cleanup or shim audit failed')
                except BaseException as caught:error=caught
            if self.process.poll() is None:
                with contextlib.suppress(ProcessLookupError):(os.killpg(self.process.pid,signal.SIGTERM) if self.new_session else self.process.terminate())
                try:self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):(os.killpg(self.process.pid,signal.SIGKILL) if self.new_session else self.process.kill())
                    self.process.wait(timeout=3)
            if self.process.stdin:self.process.stdin.close()
            if self.process.stdout:self.process.stdout.close()
            self.process=None
        if self.selector:self.selector.close();self.selector=None
        if self.lock:self.lock.close();self.lock=None
        if error:raise error

    def __exit__(self,kind,value,traceback):
        self.close(force=kind is not None)
