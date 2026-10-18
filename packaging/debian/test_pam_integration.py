#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Synthetic ownership/crash boundaries; never changes host PAM."""
from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from pam_integration import Integration,STACKS,snapshot

class PamIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.calls=[]
        for name in STACKS:
            for parent in ('etc/pam.d','var/lib/pam'):(self.root/parent).mkdir(parents=True,exist_ok=True)
            (self.root/'etc/pam.d'/('common-'+name)).write_text('auth [success=1 default=ignore] pam_unix.so\n' if name=='auth' else '# synthetic '+name+'\n')
            (self.root/'var/lib/pam'/name).write_text('Module: unix\n')
        self.manager=Integration(self.root,self.apply)
    def tearDown(self):self.tmp.cleanup()
    def apply(self,enabled):
        self.calls.append(enabled)
        (self.root/'etc/pam.d/common-auth').write_text(('auth [success=2 default=ignore] pam_fprintd.so max-tries=1 timeout=10\n' if enabled else '')+'auth [success=1 default=ignore] pam_unix.so\n')
        (self.root/'var/lib/pam/auth').write_text(('Module: fprintd\n' if enabled else '')+'Module: unix\n')
    def test_new_install_and_remove(self):
        before=snapshot(self.root);self.manager.configure();self.assertTrue(snapshot(self.root)['fingerprint'])
        self.manager.remove();self.assertEqual(snapshot(self.root),before)
    def test_preexisting_enabled_is_preserved(self):
        self.apply(True);self.calls=[];self.manager.configure();self.manager.remove();self.assertEqual(self.calls,[])
    def test_reconfigure_does_not_repeat_enable(self):
        self.manager.configure();self.manager.configure();self.assertEqual(self.calls,[True])
    def test_admin_disabled_survives_reconfigure(self):
        self.manager.configure();self.apply(False);self.calls=[];self.manager.configure();self.manager.remove();self.assertEqual(self.calls,[])
    def test_admin_changed_stack_is_not_overwritten_on_remove(self):
        self.manager.configure();p=self.root/'etc/pam.d/common-auth';p.write_text(p.read_text()+'# administrator change\n')
        self.assertEqual(self.manager.remove()['action'],'kept-administrator-modified-PAM');self.assertTrue(snapshot(self.root)['fingerprint'])
    def test_unmanaged_tool_noop_is_not_success(self):
        manager=Integration(self.root,lambda enabled:None)
        with self.assertRaisesRegex(ValueError,'not safely enabled'):manager.configure()
        self.assertFalse(snapshot(self.root)['fingerprint'])
    def test_no_password_fallback_refuses_before_update(self):
        (self.root/'etc/pam.d/common-auth').write_text('auth required pam_permit.so\n')
        with self.assertRaisesRegex(ValueError,'password fallback'):self.manager.configure()
        self.assertEqual(self.calls,[])
    def test_pending_receipt_recovers_after_completed_command(self):
        def interrupted(enabled):self.apply(enabled);raise RuntimeError('synthetic interruption')
        with self.assertRaises(RuntimeError):Integration(self.root,interrupted).configure()
        self.assertEqual(self.manager.configure()['action'],'recovered-completed-enable')
        self.manager.remove();self.assertFalse(snapshot(self.root)['fingerprint'])
    def test_pending_receipt_retries_before_command(self):
        def interrupted(enabled):raise RuntimeError('synthetic interruption')
        with self.assertRaises(RuntimeError):Integration(self.root,interrupted).configure()
        self.manager.configure();self.assertTrue(snapshot(self.root)['fingerprint'])
    def test_aborted_removal_restores_owned_profile(self):
        self.manager.configure();self.manager.remove();self.manager.restore();self.assertTrue(snapshot(self.root)['fingerprint'])
    def test_abort_restore_refuses_changed_state(self):
        self.manager.configure();self.manager.remove();p=self.root/'etc/pam.d/common-auth';p.write_text(p.read_text()+'# changed after remove\n')
        with self.assertRaisesRegex(ValueError,'changed after'):self.manager.restore()
    def test_selection_change_during_enable_is_refused(self):
        def unexpected(enabled):
            self.apply(enabled);p=self.root/'var/lib/pam/auth';p.write_text(p.read_text()+'Module: another\n')
        with self.assertRaisesRegex(ValueError,'not safely enabled'):Integration(self.root,unexpected).configure()
    def test_receipt_symlink_is_refused(self):
        self.manager.path.parent.mkdir(mode=0o700,parents=True);self.manager.path.symlink_to(self.root/'target')
        with self.assertRaisesRegex(ValueError,'unsafe PAM receipt'):self.manager.configure()
    def test_stale_safe_temporary_receipt_is_recovered(self):
        self.manager.path.parent.mkdir(mode=0o700,parents=True);temp=self.manager.path.with_suffix('.new');temp.write_text('interrupted');temp.chmod(0o600)
        self.manager.configure();self.assertTrue(snapshot(self.root)['fingerprint'])

if __name__=='__main__':unittest.main(verbosity=2)
