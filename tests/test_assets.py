#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Asset relocation and rejection before USB access; no vendor code execution."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('YML_RUNTIME_DIR',ROOT/'runtime'))
sys.path.insert(0,str(ROOT/'runtime'))
from assets import DLL_NAME,DLL_SHA,DLL_SIZE,validate_dll,check_runtime


class AssetTests(unittest.TestCase):
    def test_manifest_matches_vendor(self):
        meta=json.loads((ROOT/'vendor/source.json').read_text())
        self.assertEqual(meta['sha256'],DLL_SHA)
        self.assertEqual(meta['size'],DLL_SIZE)
        self.assertEqual(validate_dll(ROOT/'vendor'/DLL_NAME)['sha256'],DLL_SHA)
        data=(ROOT/'vendor'/DLL_NAME).read_bytes().decode('utf-16le',errors='ignore')
        self.assertIn('FileVersion\x00\x001.0.0.3738',data)
    def test_relocated_runtime(self):
        with tempfile.TemporaryDirectory(prefix='yamila-assets-') as tmp:
            runtime=Path(tmp)/'moved'
            shutil.copytree(RUNTIME,runtime)
            result=subprocess.run(['/usr/bin/python3','-I','-B',str(runtime/'broker.py'),'--check-assets'],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['vendor']['sha256'],DLL_SHA)
    def assert_bad_before_usb(self,kind):
        with tempfile.TemporaryDirectory(prefix='yamila-bad-assets-') as tmp:
            runtime=Path(tmp)/'runtime'
            shutil.copytree(RUNTIME,runtime)
            dll=runtime/'vendor'/DLL_NAME
            if kind=='missing': dll.unlink()
            elif kind=='wrong-size': dll.write_bytes(b'MZwrong')
            else:
                data=bytearray(dll.read_bytes());data[-1]^=1;dll.write_bytes(data)
            result=subprocess.run(['/usr/bin/python3','-I','-B',str(runtime/'broker.py'),'--bus','0','--address','0'],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,76,result.stderr)
            self.assertEqual(result.stdout,'')
            self.assertIn({'missing':'missing','wrong-size':'size mismatch','wrong-hash':'SHA-256 mismatch'}[kind],result.stderr)
    def test_missing_dll(self): self.assert_bad_before_usb('missing')
    def test_wrong_dll_size(self): self.assert_bad_before_usb('wrong-size')
    def test_wrong_dll_hash(self): self.assert_bad_before_usb('wrong-hash')
    def test_missing_worker(self):
        with tempfile.TemporaryDirectory(prefix='yamila-missing-worker-') as tmp:
            runtime=Path(tmp)/'runtime';shutil.copytree(RUNTIME,runtime)
            (runtime/'native-worker').unlink()
            with self.assertRaisesRegex(ValueError,'ELF missing'):
                check_runtime(runtime)


if __name__=='__main__':unittest.main(verbosity=2)
