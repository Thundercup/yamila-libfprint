#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Download only the SHA-256 pinned upstream source, without building."""
import argparse
import json
from pathlib import Path
import shutil
import urllib.request
from audit import ROOT
from build import checked_archive

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dest',type=Path,required=True);a=p.parse_args()
    lock=json.loads((ROOT/'upstream.lock.json').read_text())
    with a.dest.open('xb') as dst:
        with urllib.request.urlopen(lock['url'],timeout=60) as src:shutil.copyfileobj(src,dst)
    checked_archive(a.dest,lock)
    print('Pinned upstream SHA-256 verified')
if __name__=='__main__':main()
