#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Install/upgrade gate fixtures; never modify host integration or templates."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'packaging'))
from preflight import inspect,FILES,PACKAGE,VERSIONS


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='yamila-policy-')
        self.root=Path(self.tmp.name)
        self.write('/etc/os-release','ID=fedora\nVERSION_ID=44\n')
        self.write('/etc/passwd','root:x:0:0::/root:/bin/bash\n')
        self.write('/etc/group','root:x:0:\n')
        self.modified=False;self.version_override={};self.installed=False
    def tearDown(self):self.tmp.cleanup()
    def write(self,name,text):
        p=self.root/name.lstrip('/');p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);p.chmod(0o644);return p
    def query(self,root,*args):
        if args[0]=='-qf':return 0,PACKAGE
        if args[0]=='-V':return (1,'changed') if self.modified else (0,'')
        if args[-1] in VERSIONS:return 0,self.version_override.get(args[-1],VERSIONS[args[-1]])
        if args[-1]==PACKAGE:return (0,'present') if self.installed else (1,'not installed')
        return 1,''
    def result(self):return inspect(self.root,self.query)
    def assert_rejected(self,substring):
        result=self.result();self.assertFalse(result['compatible']);self.assertTrue(any(substring in s for s in result['failures']),result)
    def test_clean_supported_gate(self):self.assertTrue(self.result()['compatible'])
    def test_unsupported_library_version(self):
        self.version_override['libfprint']='1.95.0-1.fc44'
        result=self.result();self.assertTrue(result['compatible']);self.assertTrue(any('libfprint' in w for w in result['warnings']))
    def test_unsupported_os(self):
        self.write('/etc/os-release','ID=fedora\nVERSION_ID=45\n')
        result=self.result();self.assertTrue(result['compatible']);self.assertTrue(result['warnings'])
    def test_derivative_can_test(self):
        self.write('/etc/os-release','ID=rocky\nVERSION_ID=10\n')
        self.assertTrue(self.result()['compatible']);self.assertTrue(self.result()['warnings'])
    def test_missing_runtime_dependency_rejected(self):
        original=self.query
        self.query=lambda root,*args:(1,'') if args[-1]=='fprintd' else original(root,*args)
        self.assert_rejected('required package is missing')
    def test_version_warning_does_not_bypass_conflicts(self):
        self.version_override['fprintd']='2.0-1.fc45'
        self.write('/etc/systemd/system/fprintd.service','custom')
        self.assert_rejected('custom or masked')
        self.assertTrue(self.result()['warnings'])
    def test_old_gateway_is_rejected(self):
        self.write('/etc/systemd/system/fprintd.service.d/90-yamila-desktop.conf','[Service]\nExecStart=/old/gateway\n');self.assert_rejected('unknown fprintd drop-in')
    def test_mask_is_rejected(self):
        p=self.root/'etc/systemd/system/fprintd.service';p.parent.mkdir(parents=True);p.symlink_to('/dev/null');self.assert_rejected('masked fprintd')
    def test_runtime_override_is_rejected(self):
        self.write('/run/systemd/system/fprintd.service.d/custom.conf','[Service]\n');self.assert_rejected('unknown fprintd')
    def test_old_usb_rule_is_rejected(self):
        self.write('/etc/udev/rules.d/old.rules','ATTR{idVendor}=="2808", ATTR{idProduct}=="06fc"\n');self.assert_rejected('explicit migration')
    def test_own_unchanged_integration_is_accepted(self):
        self.installed=True
        for name,text in FILES.items():self.write(name,text)
        self.assertTrue(self.result()['compatible'])
    def test_unchanged_previous_package_config_can_upgrade(self):
        self.installed=True
        name=next(iter(FILES));self.write(name,'[Service]\nEnvironment=LD_LIBRARY_PATH=/usr/lib64/yamila-fprint\n')
        self.assertTrue(self.result()['compatible'])
    def test_modified_installed_config_is_rejected(self):
        self.installed=True;self.modified=True
        name=next(iter(FILES));self.write(name,'# locally changed\n');self.assert_rejected('verification failed')
    def test_modified_integration_is_rejected(self):
        name=next(iter(FILES));self.write(name,'[Service]\nEnvironment=LD_PRELOAD=unknown\n');self.assert_rejected('modified integration')
    def test_modified_runtime_is_rejected(self):
        self.installed=True;self.modified=True;self.assert_rejected('verification failed')
    def test_unknown_runtime_file_is_rejected(self):
        self.write('/usr/libexec/yamila-fprint/untracked.py','synthetic')
        self.query=lambda *args:(1,'') if '-qf' in args else PreflightTests.query(self,*args)
        self.assert_rejected('unknown file')
    def test_account_collision_is_rejected(self):
        self.write('/etc/passwd','yamila-fprint:x:0:0::/root:/bin/bash\n');self.assert_rejected('incompatible')
    def test_persistent_system_account_is_accepted(self):
        self.write('/etc/passwd','yamila-fprint:x:973:973::/var/empty:/usr/sbin/nologin\n')
        self.write('/etc/group','yamila-fprint:x:973:\n');self.assertTrue(self.result()['compatible'])
    def test_generated_configs_match_gate(self):
        for name,text in FILES.items():self.assertEqual((ROOT/'packaging/files'/Path(name).name).read_text(),text)


if __name__=='__main__':unittest.main(verbosity=2)
