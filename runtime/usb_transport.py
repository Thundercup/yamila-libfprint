# SPDX-License-Identifier: LGPL-2.1-or-later
"""Small ctypes binding to host libusb; fixed device and validated descriptors."""
import ctypes as C
import ctypes.util
import fcntl
import os
from pathlib import Path
import stat
import time

from protocol import Decoder, ProtocolError


class USBError(Exception):
    pass


def inspect_devices():
    found = []
    for path in sorted(Path('/sys/bus/usb/devices').glob('*')):
        try:
            if (path/'idVendor').read_text().strip() != '2808' or (path/'idProduct').read_text().strip() != '06fc':
                continue
            bus, address = (int((path/k).read_text()) for k in ('busnum', 'devnum'))
            descriptors = (path/'descriptors').read_bytes()
            if len(descriptors)<18 or descriptors[:2]!=b'\x12\x01':
                raise USBError('invalid device descriptor')
            if descriptors[8:14] != bytes.fromhex('0828fc060320'):
                raise USBError('device revision differs from captured 0x2003')
            interface = None
            endpoints = {}
            offset = 18
            while offset < len(descriptors):
                length, kind = descriptors[offset:offset+2]
                if length<2 or offset+length>len(descriptors):
                    raise USBError('invalid descriptor length')
                d=descriptors[offset:offset+length]
                if kind==4:
                    interface=(d[2],d[3])
                elif kind==5 and interface==(0,0):
                    endpoints[d[2]]=(d[3]&3,int.from_bytes(d[4:6],'little'))
                offset+=length
            if endpoints!={0x01:(2,64),0x82:(2,64)}:
                raise USBError('unexpected endpoint layout')
            if (path/'bConfigurationValue').read_text().strip()!='1':
                raise USBError('expected active configuration 1')
            node=Path(f'/dev/bus/usb/{bus:03d}/{address:03d}')
            found.append(dict(sysfs=str(path),node=str(node),bus=bus,address=address,
                              endpoints={'out':1,'in':130,'packet_size':64},
                              descriptor_hex=descriptors.hex(),
                              read_write=os.access(node,os.R_OK|os.W_OK),
                              kernel_driver=(path/f'{path.name}:1.0/driver').exists()))
        except FileNotFoundError:
            continue
    return found


class USBTransport:
    """One request outstanding; an incomplete transaction permanently poisons it."""
    def __init__(self, info, emit=lambda **event: None):
        self.info, self.emit = info, emit
        self.ctx, self.handle = C.c_void_p(), C.c_void_p()
        self.fd = None
        self.claimed = False
        self.clean = True
        self.lib = C.CDLL(ctypes_name())
        definitions = {
            'libusb_init':([C.POINTER(C.c_void_p)],C.c_int),
            'libusb_exit':([C.c_void_p],None),
            'libusb_wrap_sys_device':([C.c_void_p,C.c_ssize_t,C.POINTER(C.c_void_p)],C.c_int),
            'libusb_get_device':([C.c_void_p],C.c_void_p),
            'libusb_get_device_descriptor':([C.c_void_p,C.POINTER(C.c_ubyte)],C.c_int),
            'libusb_close':([C.c_void_p],None),
            'libusb_claim_interface':([C.c_void_p,C.c_int],C.c_int),
            'libusb_release_interface':([C.c_void_p,C.c_int],C.c_int),
            'libusb_bulk_transfer':([C.c_void_p,C.c_ubyte,C.POINTER(C.c_ubyte),C.c_int,C.POINTER(C.c_int),C.c_uint],C.c_int),
            'libusb_error_name':([C.c_int],C.c_char_p),
        }
        for name,(args,restype) in definitions.items():
            function=getattr(self.lib,name);function.argtypes=args;function.restype=restype

    def error(self, code):
        return self.lib.libusb_error_name(code).decode()

    def __enter__(self):
        try:
            if self.info['kernel_driver']:
                raise USBError('interface is owned by a kernel driver; not detaching it')
            self.fd=os.open(self.info['node'],os.O_RDWR|os.O_CLOEXEC)
            node=os.fstat(self.fd)
            expected_minor=(self.info['bus']-1)*128+self.info['address']-1
            if not stat.S_ISCHR(node.st_mode) or os.major(node.st_rdev)!=189 or os.minor(node.st_rdev)!=expected_minor:
                raise USBError('unexpected USB device node')
            fcntl.flock(self.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            code=self.lib.libusb_init(C.byref(self.ctx))
            if code<0:raise USBError(self.error(code))
            code=self.lib.libusb_wrap_sys_device(self.ctx,self.fd,C.byref(self.handle))
            if code<0:raise USBError(self.error(code))
            descriptor=(C.c_ubyte*18)()
            device=self.lib.libusb_get_device(self.handle)
            code=self.lib.libusb_get_device_descriptor(device,descriptor)
            if code<0:raise USBError(self.error(code))
            if bytes(descriptor)!=bytes.fromhex(self.info['descriptor_hex'])[:18]:
                raise USBError('opened device identity changed after inspection')
            code=self.lib.libusb_claim_interface(self.handle,0)
            if code<0:raise USBError(self.error(code))
            self.claimed=True
            self.emit(event='usb_open',node=self.info['node'])
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.handle:
            if self.claimed:
                code=self.lib.libusb_release_interface(self.handle,0)
                self.emit(event='usb_release',result=code)
            self.lib.libusb_close(self.handle)
            self.handle=C.c_void_p();self.claimed=False
        if self.ctx:
            self.lib.libusb_exit(self.ctx);self.ctx=C.c_void_p()
        if self.fd is not None:
            os.close(self.fd);self.fd=None

    def __exit__(self,*args):
        self.close()

    def exchange(self, request):
        if not self.clean:
            raise USBError('incomplete previous transaction; reconnect before retrying')
        self.clean=False
        sent=C.c_int()
        buffer=(C.c_ubyte*len(request)).from_buffer_copy(request)
        code=self.lib.libusb_bulk_transfer(self.handle,1,buffer,len(request),C.byref(sent),1000)
        if code<0 or sent.value!=len(request):
            raise USBError(f'write {self.error(code)} bytes={sent.value}/{len(request)}')
        decoder=Decoder()
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            # Packet aligned buffer; never request a tiny header-sized bulk read.
            response=(C.c_ubyte*16384)();received=C.c_int()
            timeout=max(1,min(250,int((deadline-time.monotonic())*1000)))
            code=self.lib.libusb_bulk_transfer(self.handle,0x82,response,len(response),C.byref(received),timeout)
            if code not in (0,-7):
                raise USBError(f'read {self.error(code)} bytes={received.value}')
            if received.value:
                frames=decoder.feed(bytes(response[:received.value]))
                if frames:
                    if len(frames)!=1 or decoder.buffer:
                        raise ProtocolError('unexpected extra or partial response after reply')
                    self.clean=True
                    return frames[0]
        raise USBError(f'response timeout; partial_bytes={len(decoder.buffer)}; reconnect required')


def ctypes_name():
    # Fixed ELF SONAME on the supported Fedora target. ctypes.util.find_library
    # spawns ldconfig/compiler helpers, which the confined daemon must not run.
    return 'libusb-1.0.so.0'
