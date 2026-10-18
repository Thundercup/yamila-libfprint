#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Publication boundary checks, using only copies of the public allowlist."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from audit import audit,MANIFEST


class PublicBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='yamila-public-audit-')
        self.root=Path(self.tmp.name)/'source'
        self.root.mkdir()
        items=json.loads((ROOT/'public-files.json').read_text())['files']
        for name in [i['path'] for i in items]+[MANIFEST]:
            dest=self.root/name;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/name,dest)
    def tearDown(self):self.tmp.cleanup()
    def test_unlisted_data_is_rejected(self):
        (self.root/'unexpected.raw16').write_bytes(b'synthetic')
        with self.assertRaisesRegex(ValueError,'allowlist mismatch'):audit(self.root)
    def test_source_symlink_is_rejected(self):
        p=self.root/'README.md';p.unlink();p.symlink_to('NOTICE.md')
        with self.assertRaisesRegex(ValueError,'symlink'):audit(self.root)
    def test_modified_source_is_rejected(self):
        with (self.root/'README.md').open('a') as f:f.write('\nModified\n')
        with self.assertRaisesRegex(ValueError,'digest mismatch'):audit(self.root)
    def test_developer_path_is_rejected_even_on_refresh(self):
        with (self.root/'README.md').open('a') as f:f.write('/ho'+'me/example/fingerprint')
        with self.assertRaisesRegex(ValueError,'developer path'):audit(self.root,write=True)
    def test_allowlist_escape_is_rejected(self):
        p=self.root/'public-files.json';data=json.loads(p.read_text())
        data['files'][0]['path']='../escape'
        p.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'invalid allowlist'):audit(self.root)
    def test_export_excludes_generated_directories(self):
        (self.root/'build').mkdir();(self.root/'build'/'generated.raw16').write_bytes(b'synthetic')
        (self.root/'.cache').mkdir();(self.root/'.cache'/'cached.key').write_bytes(b'synthetic')
        dest=Path(self.tmp.name)/'export'
        result=subprocess.run(['/usr/bin/python3','-B',str(self.root/'tools/export.py'),'--dest',str(dest)],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        audit(dest)
        self.assertFalse((dest/'build').exists());self.assertFalse((dest/'.cache').exists())
    def test_export_excludes_git_metadata(self):
        (self.root/'.git').mkdir()
        (self.root/'.git/config').write_text('synthetic metadata, never public source')
        dest=Path(self.tmp.name)/'git-export'
        result=subprocess.run(['/usr/bin/python3','-B',str(self.root/'tools/export.py'),'--dest',str(dest)],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        audit(dest)
        self.assertFalse((dest/'.git').exists())
    def test_allowlist_cannot_select_git_metadata(self):
        (self.root/'.git').mkdir();(self.root/'.git/config').write_text('synthetic')
        p=self.root/'public-files.json';data=json.loads(p.read_text())
        data['files'][0]['path']='.git/config';p.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'invalid allowlist'):audit(self.root)


if __name__=='__main__':unittest.main(verbosity=2)
