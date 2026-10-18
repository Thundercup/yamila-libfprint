#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Private YML1 pipe broker; no socket, no template files, no raw-image logging."""
import argparse
import ctypes
import fcntl
import os
from pathlib import Path
import signal
import struct
import sys
import threading
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from bridge import BridgeError, validate_record
from native_bridge import NativeEngineWorker
from assets import check_runtime
os.environ["YML_ENGINE_PARENT_PID"] = str(os.getpid())
from protocol import Capture, Cancelled
from usb_transport import USBTransport, inspect_devices

MAX = 12 + 2*1024*1024 + 4096*4 + 1024*1024
stopped = threading.Event()
worker_pid = None
parent_pid = os.getppid()


def frame(kind, body=b''):
    if len(body) > MAX:
        raise ValueError('oversized reply')
    sys.stdout.buffer.write(struct.pack('<BI', ord(kind), len(body)) + body)
    sys.stdout.buffer.flush()


def exact(count):
    data = bytearray()
    while len(data) < count:
        chunk = sys.stdin.buffer.read(count-len(data))
        if not chunk:
            raise EOFError()
        data.extend(chunk)
    return bytes(data)


def unpack_record(data):
    if len(data) < 12:
        raise ValueError('short record')
    size, indices, payload = struct.unpack('<III', data[:12])
    if not 1 <= size <= 2*1024*1024 or indices > 4096 or payload > 1024*1024 or len(data) != 12+size+indices*4+payload:
        raise ValueError('invalid record')
    record = dict(template_hex=data[12:12+size].hex(),
                  index_hex=data[12+size:12+size+indices*4].hex(),
                  payload_hex=data[12+size+indices*4:].hex())
    validate_record(record)
    return record


def stop(*_):
    stopped.set()
    # The worker joins this broker's process group; the parent kills the group
    # on cancellation. Also handle parent death independently of pipe reads.
    if worker_pid:
        try:
            os.kill(worker_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def watch_parent():
    while not stopped.wait(.1):
        if os.getppid() != parent_pid:
            stop()
            os._exit(70)


class Done(Exception):
    pass


def check_engine(lock):
    """Fail before requesting images if sandbox/algorithm initialization fails."""
    global worker_pid
    try:
        with NativeEngineWorker(new_session=False, lock_path=lock) as engine:
            worker_pid = engine.process.pid
            engine.begin()  # In-memory begin/discard, no Capture or image input.
    finally:
        worker_pid = None


def run_real(mode, body, channel, lock):
    global worker_pid
    cleanup_failed = False
    def audit(**event):
        nonlocal cleanup_failed
        if event.get('event') == 'cleanup_error' or (event.get('event') == 'usb_release' and event.get('result') != 0):
            cleanup_failed = True
    updates = 0
    record = None
    result_match = None
    result_retry = False
    try:
        with NativeEngineWorker(new_session=False, lock_path=lock) as engine:
            worker_pid = engine.process.pid
            if mode == 1:
                engine.begin()
            else:
                engine.load(unpack_record(body))
            capture = Capture(channel, audit, stopped.is_set)
            def submit(index, raw):
                nonlocal updates, result_match, result_retry
                if stopped.is_set():
                    raise Cancelled('cancelled')
                if mode == 1:
                    result = engine.enroll(raw)
                    hr = result['hresult']
                    if hr in ('0x00000000', '0x00090001'):
                        updates += 1
                        # Completion is emitted only after commit + engine cleanup.
                        if not result['complete']:
                            frame('P', struct.pack('<I', min(updates, 11)))
                    elif hr == '0x80098008':
                        frame('N')  # retry, no stage increment
                    else:
                        raise BridgeError('enrollment engine failure')
                    if hr == '0x00000000' and result['complete']:
                        raise Done()
                else:
                    result = engine.verify(raw)
                    hr = result['hresult']
                    if hr == '0x80098008':
                        result_retry = True
                        return
                    if hr not in ('0x00000000', '0x80098005') or result['match'] != (hr == '0x00000000'):
                        raise BridgeError('inconsistent verification result')
                    result_match = result['match']
            try:
                capture.images(60 if mode == 1 else 1, 180 if mode == 1 else 30, submit)
                if mode == 1:
                    raise BridgeError('enrollment incomplete')
            except Done:
                pass
            if cleanup_failed or capture.active or stopped.is_set():
                raise BridgeError('capture cleanup failed or cancelled')
            if mode == 1:
                record = validate_record(engine.commit())
    finally:
        worker_pid = None
    if stopped.is_set():
        raise Cancelled('cancelled before result')
    if result_retry:
        frame('N')
    else:
        frame('T' if mode == 1 else 'M', record if mode == 1 else bytes([int(result_match)]))


def run_mock(mode, body, scenario):
    if scenario == 'crash':
        os._exit(71)
    if scenario == 'malformed':
        sys.stdout.buffer.write(struct.pack('<BI', ord('T'), MAX+1))
        sys.stdout.buffer.flush()
        return
    if scenario in ('hang', 'late'):
        stopped.wait(5)
        # Deliberately ignore cancellation to exercise parent's late-result guard.
    if mode == 1:
        for stage in range(1, 12):
            frame('P', struct.pack('<I', stage))
        template = (b'SYNTHETIC-TEMPLATE-NO-BIOMETRICS!!' * 32768)[:1024*1024]
        frame('T', struct.pack('<III', len(template), 1, 0)+template+b'\x00'*4)
    else:
        unpack_record(body)
        frame('M', bytes([scenario != 'no-match']))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mock')
    parser.add_argument('--check-assets', action='store_true')
    parser.add_argument('--bus', type=int)
    parser.add_argument('--address', type=int)
    args = parser.parse_args()
    global worker_pid
    idle_engine = None
    os.umask(0o077)
    if os.geteuid() == 0:
        return 77  # Never load vendor code as root, including direct invocation.
    try:
        assets = check_runtime(HERE)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 76
    if args.check_assets:
        import json
        print(json.dumps(assets, sort_keys=True))
        return 0
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, stop)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0 or os.getppid() != parent_pid:
        return 78
    threading.Thread(target=watch_parent, daemon=True).start()
    channel = None
    lock_file = None
    failed = False
    try:
        if args.mock:
            # Test-only directory, not consulted by production USB class.
            directory = Path(args.mock)
            if directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077:
                raise ValueError('mock directory must be private')
            lock_file = open(directory / 'device.lock', 'a')
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            scenario = (directory / 'scenario').read_text().strip()
            if scenario == 'native-idle':
                idle_engine = NativeEngineWorker(new_session=False, lock_path=directory / 'worker.lock')
                idle_engine.__enter__()
                worker_pid = idle_engine.process.pid
                idle_engine.begin()
                (directory / 'worker.pid').write_text(str(worker_pid))
                (directory / 'broker.pid').write_text(str(os.getpid()))
        else:
            devices = [d for d in inspect_devices() if d['bus'] == args.bus and d['address'] == args.address]
            if len(devices) != 1:
                raise ValueError('USB identity changed')
            channel = USBTransport(devices[0])
            channel.__enter__()  # Kernel interface claim is the hardware exclusion.
            Capture(channel).probe()
            # Worker locks have no persistent template state.
            lock_file = tempfile.TemporaryDirectory(prefix='yamila-worker-')
            check_engine(Path(lock_file.name) / 'worker.lock')
        frame('R', b'YML1')
        while not stopped.is_set():
            mode, size = struct.unpack('<BI', exact(5))
            if size > MAX or mode not in (1, 2, 3) or (mode != 2 and size):
                raise ValueError('invalid operation')
            body = exact(size)
            if mode == 3:
                if channel:
                    channel.close()
                    channel = None
                if idle_engine:
                    idle_engine.close()
                    idle_engine = None
                    worker_pid = None
                frame('C')
                return 0
            if args.mock:
                run_mock(mode, body, scenario)
            else:
                run_real(mode, body, channel, Path(lock_file.name) / 'worker.lock')
    except (Exception,):
        # Release USB/locks before reporting failure: the caller may terminate
        # this process immediately after receiving the error frame.
        failed = True
    finally:
        stop()
        if idle_engine:
            idle_engine.close(force=True)
        if channel:
            channel.close()
        if lock_file:
            if args.mock:
                lock_file.close()
            else:
                lock_file.cleanup()
    if failed:
        # Error bodies contain no engine output, template or sample data.
        try:
            frame('E', b'broker operation failed')
        except (BrokenPipeError, OSError):
            pass
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
