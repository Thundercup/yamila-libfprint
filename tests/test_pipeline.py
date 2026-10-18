#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Synthetic capture/engine orchestration plus actual DLL lifecycle, no USB I/O."""
import os
import shutil
from pathlib import Path
import signal
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.environ.get("YML_RUNTIME_DIR", str(HERE / "runtime")))
import broker
from protocol import Frame, ProtocolError
from bridge import BridgeError, validate_record

RECORD = dict(template_hex=(b'SYNTHETIC'*4).hex(), index_hex='00000000', payload_hex='')


class SyntheticChannel:
    clean = True
    def __init__(self, bad_finish=False):
        self.release = False
        self.finished = False
        self.bad_finish = bad_finish
    def exchange(self, request):
        code, data = request[3], request[4:-1]
        if code == 0x34:
            answer = b'\x55\xaa'
        elif code == 0x80 and data == b'\x01\x02':
            answer = b'\xa5\x5a'
        elif code == 0x80 and data == b'\x02\x01':
            answer = b'\x00' if self.release else b'\x01'
            self.release = False
        elif code == 0x82 and data == b'\x73\x01':
            answer = b'\x05'
        elif code == 0x81:
            answer = bytes(10240)
            self.release = True
        elif code == 0x82 and data == b'\x78\x01':
            if self.bad_finish:
                raise ProtocolError('synthetic finish failure')
            self.finished = True
            answer = b''
        else:
            raise AssertionError('unexpected capture command')
        return Frame(4, answer, 0)


class SyntheticEngine:
    samples = 0
    committed = False
    closed = False
    cleanup_failure = False
    verify_result = dict(hresult='0x00000000', match=True)
    def __init__(self, **kwargs):
        self.process = type('Process', (), dict(pid=99999999))()
    def __enter__(self):
        return self
    def __exit__(self, *_):
        type(self).closed = True
        if self.cleanup_failure:
            raise BridgeError('synthetic worker cleanup failure')
    def begin(self):
        pass
    def enroll(self, raw):
        self.assert_raw(raw)
        self.samples += 1
        done = self.samples == 12
        return dict(hresult='0x00000000' if done else '0x00090001', complete=done)
    @staticmethod
    def assert_raw(raw):
        assert raw == bytes(10240)
    def commit(self):
        type(self).committed = True
        return RECORD
    def load(self, record):
        assert record == RECORD
    def verify(self, raw):
        self.assert_raw(raw)
        return self.verify_result


class PipelineTests(unittest.TestCase):
    def setUp(self):
        broker.stopped.clear()
        SyntheticEngine.committed = SyntheticEngine.closed = SyntheticEngine.cleanup_failure = False
        SyntheticEngine.verify_result = dict(hresult='0x00000000', match=True)
        self.frames = []
    def run_pipeline(self, mode, channel=None):
        def collect(kind, body=b''):
            if kind in ('T', 'M', 'N') and kind != 'N':
                self.assertTrue(SyntheticEngine.closed, 'result before engine cleanup')
            self.frames.append((kind, body))
        with patch.object(broker, 'NativeEngineWorker', SyntheticEngine), patch.object(broker, 'frame', collect):
            broker.run_real(mode, b'' if mode == 1 else validate_record(RECORD), channel or SyntheticChannel(), '/unused-synthetic-lock')
    def test_capture_enroll_commit_cleanup(self):
        channel = SyntheticChannel()
        self.run_pipeline(1, channel)
        self.assertTrue(channel.finished)
        self.assertEqual([struct.unpack('<I', b)[0] for k, b in self.frames if k == 'P'], list(range(1, 12)))
        self.assertEqual(self.frames[-1], ('T', validate_record(RECORD)))
    def test_finish_failure_never_commits(self):
        with self.assertRaises(BridgeError):
            self.run_pipeline(1, SyntheticChannel(bad_finish=True))
        self.assertFalse(SyntheticEngine.committed)
        self.assertFalse(any(k == 'T' for k, _ in self.frames))
    def test_engine_cleanup_failure_suppresses_template(self):
        SyntheticEngine.cleanup_failure = True
        with self.assertRaises(BridgeError):
            self.run_pipeline(1)
        self.assertFalse(any(k == 'T' for k, _ in self.frames))
    def test_match_mismatch_retry(self):
        for result, expected in [(dict(hresult='0x00000000', match=True), ('M', b'\x01')),
                                 (dict(hresult='0x80098005', match=False), ('M', b'\x00')),
                                 (dict(hresult='0x80098008', match=False), ('N', b''))]:
            SyntheticEngine.verify_result = result
            self.run_pipeline(2)
            self.assertEqual(self.frames[-1], expected)
    def test_inconsistent_engine_result_is_error(self):
        SyntheticEngine.verify_result = dict(hresult='0x80098005', match=True)
        with self.assertRaises(BridgeError):
            self.run_pipeline(2)
        self.assertFalse(any(k == 'M' for k, _ in self.frames))
    def test_record_bounds(self):
        for data in (b'', struct.pack('<III', 0, 0, 0), struct.pack('<III', 2**32-1, 0, 0)):
            with self.assertRaises(ValueError):
                broker.unpack_record(data)
        self.assertEqual(broker.unpack_record(validate_record(RECORD)), RECORD)


class NativeLifecycleTests(unittest.TestCase):
    def test_open_algorithm_check_without_images(self):
        with tempfile.TemporaryDirectory(prefix='yamila-open-offline-') as tmp:
            broker.check_engine(Path(tmp)/'engine.lock')
        self.assertIsNone(broker.worker_pid)
    def test_fixed_dll_begin_discard(self):
        # This is a real vendor DLL initialization/cleanup, without image input.
        with tempfile.TemporaryDirectory(prefix='yamila-native-offline-') as tmp:
            with broker.NativeEngineWorker(new_session=False, lock_path=Path(tmp)/'engine.lock') as engine:
                engine.begin()
            self.assertEqual(engine.native_audit['imports_resolved'], 107)
            self.assertEqual(engine.native_audit['unsupported_calls'], 0)
    def test_relocated_native_worker(self):
        with tempfile.TemporaryDirectory(prefix='yamila-moved-native-') as tmp:
            runtime=Path(tmp)/'runtime'
            shutil.copytree(Path(os.environ['YML_RUNTIME_DIR']),runtime)
            code = "import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); from native_bridge import NativeEngineWorker; import os; os.environ['YML_ENGINE_PARENT_PID']=str(os.getpid()); w=NativeEngineWorker(new_session=False,lock_path=Path(sys.argv[2])); w.__enter__(); w.begin(); w.close(); assert w.native_audit['unsupported_calls']==0"
            result=subprocess.run(['/usr/bin/python3','-I','-B','-c',code,str(runtime),str(Path(tmp)/'worker.lock')],capture_output=True,text=True,timeout=10,env={**os.environ,'YML_ENGINE_PARENT_PID':str(os.getpid())})
            self.assertEqual(result.returncode,0,result.stderr)
    def test_client_exit_stops_broker_and_real_worker(self):
        with tempfile.TemporaryDirectory(prefix='yamila-parent-exit-') as tmp:
            directory = Path(tmp)
            (directory/'scenario').write_text('native-idle')
            client = subprocess.run([str(Path(os.environ["YML_TEST_BINARY"]))],
                                     env={**os.environ, 'YAMILA_ABANDON_DIR':tmp},
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
            self.assertEqual(client.returncode, 0, client.stderr.decode())
            pids = [int((directory/name).read_text()) for name in ('worker.pid', 'broker.pid')]
            def running(pid):
                try:
                    return Path(f'/proc/{pid}/stat').read_text().split()[2] != 'Z'
                except FileNotFoundError:
                    return False
            deadline = time.monotonic()+3
            while any(running(pid) for pid in pids) and time.monotonic() < deadline:
                time.sleep(.02)
            try:
                self.assertFalse(any(running(pid) for pid in pids), 'orphan process remains active')
            finally:
                for pid in pids:
                    if running(pid):
                        os.kill(pid, signal.SIGKILL)


if __name__ == '__main__':
    unittest.main(verbosity=2)
