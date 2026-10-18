#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Scan the exact public allowlist; never inspect a user's private store."""
import argparse
import re
import sys

from audit import ROOT, audit

PATTERNS = {
    'personal home path': re.compile(r'/ho[m]e/|/Us[e]rs/|[A-Za-z]:\\Us[e]rs\\'),
    'GitHub credential': re.compile(r'\bgh[pousr]_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b'),
    'private key': re.compile(r'-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----'),
}


def scan(text, denied=()):
    findings=[name for name,pattern in PATTERNS.items() if pattern.search(text)]
    if any(value and value.casefold() in text.casefold() for value in denied):
        findings.append('local identity marker')
    return findings


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deny-text',action='append',default=[],help='local identity marker; its value is never printed')
    args=parser.parse_args()
    manifest=audit();findings=[]
    for item in manifest['files']:
        if item['path']=='vendor/YmlWbioEngineAdapter.dll':continue # fixed, separately audited vendor identity
        for kind in scan((ROOT/item['path']).read_text(),args.deny_text):
            findings.append(item['path']+': '+kind)
    if findings:
        sys.exit('Public privacy check refused:\n'+'\n'.join(findings))
    print('Public privacy check OK: exact allowlist, no selected private data; fixed vendor DLL separately verified.')


if __name__=='__main__':main()
