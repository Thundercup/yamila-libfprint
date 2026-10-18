#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Synthetic privacy markers, assembled to keep fixtures independently clean."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from privacy_check import scan
class PrivacyTests(unittest.TestCase):
    def test_clean(self):self.assertEqual(scan('ordinary source'),[])
    def test_local_identity(self):self.assertIn('local identity marker',scan('Example Person',('example person',)))
    def test_home(self):self.assertIn('personal home path',scan('/ho'+'me/example/source'))
    def test_credential(self):self.assertIn('GitHub credential',scan('gh'+'p_'+'x'*32))
    def test_key(self):self.assertIn('private key',scan('-----BEGIN '+'PRIVATE KEY-----'))
if __name__=='__main__':unittest.main(verbosity=2)
