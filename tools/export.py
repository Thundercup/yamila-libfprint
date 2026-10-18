#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Export only audited files, never a recursive workspace or build copy."""
import argparse
from pathlib import Path
import shutil
from audit import ROOT,audit,MANIFEST

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dest',type=Path,required=True)
    args=parser.parse_args()
    dest=args.dest.absolute()
    if dest.exists() or dest.is_symlink():parser.error('--dest must be new')
    data=audit()
    dest.mkdir(parents=True)
    for item in data['files']+[dict(path=MANIFEST)]:
        src=ROOT/item['path'];target=dest/item['path']
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(src,target);target.chmod(0o644)
    audit(dest)
    print('Exported '+str(len(data['files'])+1)+' audited files to '+str(dest))
