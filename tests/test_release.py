#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Public link boundaries; all fixtures are synthetic temporary documents."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from release_check import check_links


class ReleaseLinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)/'public'
        self.root.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_nested_relative_anchor(self):
        (self.root/'docs').mkdir()
        (self.root/'docs/guide.md').write_text('# Guide\n[Main](../README.md#known-limits)\n')
        (self.root/'README.md').write_text('# Main\n## Known limits\n[Guide](docs/guide.md)\n')
        self.assertEqual(check_links(self.root), 2)

    def test_existing_private_target_outside_export_is_rejected(self):
        (self.root.parent/'outside.md').write_text('synthetic private fixture')
        (self.root/'README.md').write_text('[Wrong](../outside.md)')
        with self.assertRaisesRegex(ValueError, 'escapes public source'):
            check_links(self.root)

    def test_missing_target_is_rejected(self):
        (self.root/'README.md').write_text('[Missing](missing.md)')
        with self.assertRaisesRegex(ValueError, 'missing link target'):
            check_links(self.root)

    def test_missing_anchor_is_rejected(self):
        (self.root/'README.md').write_text('# Main\n[Missing](#unknown)')
        with self.assertRaisesRegex(ValueError, 'missing local anchor'):
            check_links(self.root)

    def test_active_url_scheme_is_rejected(self):
        (self.root/'README.md').write_text('[Wrong](javascript:alert)')
        with self.assertRaisesRegex(ValueError, 'unsupported link'):
            check_links(self.root)


if __name__ == '__main__':
    unittest.main(verbosity=2)
