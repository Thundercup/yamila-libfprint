#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Policy ownership boundaries using synthetic module stores only."""
from pathlib import Path
from types import SimpleNamespace
import sys,tempfile,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'packaging'))
import selinux_policy as policy

class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.file=Path(self.tmp.name)/'module.pp';self.file.write_bytes(b'SYNTHETIC-POLICY')
        self.listing='200 yamila_libfprint pp\n';self.content=b'SYNTHETIC-POLICY';self.code=0
        self.path_patch=patch.object(policy,'POLICY_PATH',self.file);self.path_patch.start()
        self.config_patch=patch.object(policy,'policy_configured',return_value=True);self.config_patch.start()
    def tearDown(self):self.config_patch.stop();self.path_patch.stop();self.tmp.cleanup()
    def fake_run(self,cmd,**kw):
        if '-lfull' in cmd:return SimpleNamespace(returncode=self.code,stdout=self.listing)
        (Path(kw['cwd'])/'yamila_libfprint.pp').write_bytes(self.content)
        return SimpleNamespace(returncode=0,stdout='')
    def test_owned_policy_is_accepted(self):self.assertEqual(policy.policy_errors(run=self.fake_run),[])
    def test_unknown_module_without_file_is_rejected(self):
        self.file.unlink();self.assertIn('without package policy file',policy.policy_errors(run=self.fake_run)[0])
    def test_administrator_changes_are_rejected(self):
        self.content=b'LOCAL-MODIFICATION';self.assertIn('administrator-modified',policy.policy_errors(run=self.fake_run)[0])
    def test_priority_override_is_rejected(self):
        self.listing='400 yamila_libfprint pp\n';self.assertIn('priority',policy.policy_errors(run=self.fake_run)[0])
    def test_administrator_disabled_module_is_rejected(self):
        self.listing='200 yamila_libfprint pp disabled\n';self.assertTrue(policy.policy_errors(run=self.fake_run))
    def test_multiple_modules_are_rejected(self):
        self.listing+='400 yamila_libfprint pp\n';self.assertIn('multiple',policy.policy_errors(run=self.fake_run)[0])
    def test_unreadable_store_is_rejected(self):
        self.code=1;self.assertIn('administrator privileges',policy.policy_errors(run=self.fake_run)[0])
    def test_missing_module_is_not_an_ownership_conflict(self):
        self.listing='100 unrelated pp\n';self.assertEqual(policy.policy_errors(run=self.fake_run),[])

if __name__=='__main__':unittest.main(verbosity=2)
