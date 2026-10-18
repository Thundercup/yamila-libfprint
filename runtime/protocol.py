# SPDX-License-Identifier: LGPL-2.1-or-later
"""2808:06fc framing and capture flow, derived from local Windows captures.

No firmware/template operations. Trailers are preserved, not interpreted.
"""
from dataclasses import dataclass
from functools import reduce
import operator
import struct
import sys
import time

MAX_BODY = 10241
WIDTH, HEIGHT = 64, 80
COMMANDS = {
    'handshake': (0x34, b''), 'version': (0x30, b''),
    'width': (0x80, b'\x03\x01'), 'height': (0x80, b'\x04\x01'),
    'wake': (0x80, b'\x01\x02'), 'poll': (0x80, b'\x02\x01'),
    'prepare_image': (0x82, b'\x73\x01'), 'image': (0x81, b''),
    'finish': (0x82, b'\x78\x01'),
}


class ProtocolError(Exception):
    pass


class Cancelled(Exception):
    pass


class CaptureTimeout(Exception):
    pass


def encode(code, data=b''):
    body = bytes([code]) + bytes(data)
    if not 1 <= len(body) <= MAX_BODY:
        raise ProtocolError('body length outside supported range')
    message = len(body).to_bytes(2, 'big') + body
    return b'\x02' + message + bytes([reduce(operator.xor, message, 0)])


@dataclass(frozen=True)
class Frame:
    code: int
    data: bytes
    trailer: int | None


class Decoder:
    """Incremental decoder; errors are terminal, no speculative resync in pixels."""
    def __init__(self, incoming=True):
        self.incoming = incoming
        self.buffer = bytearray()
        self.failed = False

    def feed(self, data):
        if self.failed:
            raise ProtocolError('decoder already failed')
        self.buffer.extend(data)
        frames = []
        try:
            while self.buffer:
                if self.buffer[0] != 2:
                    raise ProtocolError('unexpected start byte')
                if len(self.buffer) < 3:
                    break
                length = int.from_bytes(self.buffer[1:3], 'big')
                if not 1 <= length <= MAX_BODY:
                    raise ProtocolError('declared body length outside supported range')
                canonical = length + 4
                total = canonical + int(self.incoming)
                if len(self.buffer) < total:
                    break
                if reduce(operator.xor, self.buffer[1:canonical], 0):
                    raise ProtocolError('XOR checksum mismatch')
                frames.append(Frame(self.buffer[3], bytes(self.buffer[4:canonical-1]),
                                    self.buffer[canonical] if self.incoming else None))
                del self.buffer[:total]
            if len(self.buffer) > MAX_BODY + 5:
                raise ProtocolError('receive buffer exceeded bound')
        except ProtocolError:
            self.failed = True
            raise
        return frames

    def finish(self):
        if self.failed or self.buffer:
            raise ProtocolError('truncated or invalid frame')


def image_words(data):
    if len(data) != WIDTH * HEIGHT * 2:
        raise ProtocolError('unexpected image byte count')
    words = struct.unpack('<5120H', data)
    if max(words) > 1023:
        raise ProtocolError('image has values outside observed 10-bit range')
    return words


class Capture:
    def __init__(self, channel, emit=lambda **event: None, cancelled=lambda: False,
                 now=time.monotonic, sleep=time.sleep):
        self.channel, self.emit = channel, emit
        self.cancelled, self.now, self.sleep = cancelled, now, sleep
        self.active = False

    def command(self, name, expected=None):
        code, data = COMMANDS[name]
        reply = self.channel.exchange(encode(code, data))
        self.emit(event='command', name=name, response_code=reply.code,
                  response_bytes=len(reply.data), trailer=reply.trailer,
                  response_hex=reply.data.hex() if len(reply.data)<=128 else None)
        if reply.code != 4:
            raise ProtocolError(f'{name}: unexpected response code {reply.code:02x}')
        if expected is not None and reply.data != expected:
            raise ProtocolError(f'{name}: unexpected response data {reply.data.hex()}')
        return reply.data

    def probe(self):
        self.command('handshake', b'\x55\xaa')
        version = self.command('version')
        if not version or len(version) > 128:
            raise ProtocolError('invalid version length')
        self.command('width', bytes([WIDTH]))
        self.command('height', bytes([HEIGHT]))
        return version.decode('ascii', errors='backslashreplace')

    def check(self, deadline):
        if self.cancelled():
            raise Cancelled('capture cancelled')
        if self.now() >= deadline:
            raise CaptureTimeout('finger wait timed out')

    def finish(self):
        if self.active:
            # Do not send another request while a previous reply is incomplete.
            if not self.channel.clean:
                raise ProtocolError('channel desynchronized; close and reconnect device')
            self.command('finish', b'')
            self.active = False

    def images(self, count, seconds, save):
        deadline = self.now() + seconds
        try:
            self.command('handshake', b'\x55\xaa')
            # Mark active before sending so even a bad wake reply is cleaned up.
            self.active = True
            self.command('wake', b'\xa5\x5a')
            self.emit(event='waiting_for_finger')
            for index in range(count):
                self.check(deadline)
                while True:
                    self.check(deadline)
                    state = self.command('poll')
                    if state == b'\x01':
                        break
                    if state != b'\x00':
                        raise ProtocolError(f'unknown contact state {state.hex()}')
                    self.sleep(0.05)
                # UMDF RVA0x58fc queries 82/7301; caller at0xcd30
                # only proceeds on05 and sleeps30ms otherwise. Linux also
                # observed06: retain it as a not-ready observation, not success.
                image_deadline = min(deadline, self.now() + 3)
                while True:
                    self.check(image_deadline)
                    ready = self.command('prepare_image')
                    if ready == b'\x05':
                        break
                    if ready != b'\x06':
                        raise ProtocolError(f'unknown image readiness {ready.hex()}')
                    self.sleep(0.03)
                raw = self.command('image')
                image_words(raw)
                save(index, raw)
                self.emit(event='image', index=index, bytes=len(raw))
                # Release is needed between images, not after the last image.
                if index == count - 1:
                    break
                while True:
                    self.check(deadline)
                    state = self.command('poll')
                    if state == b'\x00':
                        break
                    if state != b'\x01':
                        raise ProtocolError(f'unknown release state {state.hex()}')
                    self.sleep(0.05)
            return count
        finally:
            pending_error = sys.exc_info()[0] is not None
            try:
                self.finish()
            except Exception as error:
                self.emit(event='cleanup_error',reason=str(error))
                if not pending_error:
                    raise
