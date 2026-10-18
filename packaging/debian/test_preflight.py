#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Synthetic Debian transaction boundaries; no host package operations."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from preflight import FILES, PACKAGE, inspect

class UbuntuGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.write('/etc/os-release','ID=ubuntu\nVERSION_ID="26.04"\n')
        self.write('/etc/passwd','root:x:0:0:root:/root:/bin/sh\n')
        self.write('/etc/group','root:x:0:\n')
        self.write('/usr/lib/systemd/system/fprintd.service','synthetic unit')
        self.baseline={'packages':{'fprintd':'1.2','libfprint-2-2':'3.4'},'unit_sha256':hashlib.sha256(b'synthetic unit').hexdigest()}
        self.installed=False;self.modified=False;self.owned=False
    def tearDown(self):self.tmp.cleanup()
    def write(self,name,data):
        p=self.root/name.lstrip('/');p.parent.mkdir(parents=True,exist_ok=True);p.write_text(data)
    def query(self,root,operation,value):
        if operation=='version':return (0,self.baseline['packages'][value])
        if operation=='status':return (0,'install ok installed') if self.installed else (1,'')
        if operation=='owner':return (0,PACKAGE+': '+value) if self.owned else (1,'')
        if operation=='verify':return (0,'modified') if self.modified else (0,'')
        raise AssertionError(operation)
    def result(self):return inspect(self.baseline,self.root,self.query)
    def test_clean(self):self.assertTrue(self.result()['compatible'])
    def test_wrong_distribution(self):
        self.write('/etc/os-release','ID=ubuntu\nVERSION_ID=24.04\n');self.assertFalse(self.result()['compatible'])
    def test_changed_native_unit(self):
        self.write('/usr/lib/systemd/system/fprintd.service','changed');self.assertFalse(self.result()['compatible'])
    def test_custom_unit(self):
        self.write('/etc/systemd/system/fprintd.service','override');self.assertFalse(self.result()['compatible'])
    def test_unknown_vendor_dropin(self):
        self.write('/usr/lib/systemd/system/fprintd.service.d/override.conf','unknown');self.assertFalse(self.result()['compatible'])
    def test_unowned_integration(self):
        for name,value in FILES.items():self.write(name,value)
        self.assertFalse(self.result()['compatible'])
    def test_clean_upgrade(self):
        self.installed=self.owned=True
        for name,value in FILES.items():self.write(name,value)
        self.assertTrue(self.result()['compatible'])
    def test_modified_upgrade(self):
        self.installed=self.owned=self.modified=True;self.assertFalse(self.result()['compatible'])
    def test_foreign_usb_rule(self):
        self.write('/etc/udev/rules.d/custom.rules','2808 06fc');self.assertFalse(self.result()['compatible'])
    def test_root_worker_account(self):
        self.write('/etc/passwd','yamila-fprint:x:0:0:bad:/var/empty:/usr/sbin/nologin\n')
        self.write('/etc/group','yamila-fprint:x:0:\n');self.assertFalse(self.result()['compatible'])
    def test_apparmor_refuses_without_disabling(self):
        self.write('/sys/kernel/security/apparmor/profiles','/usr/libexec/fprintd (enforce)\n')
        self.assertFalse(self.result()['compatible']);self.assertFalse(self.result()['changes_performed'])

if __name__=='__main__':unittest.main(verbosity=2)
