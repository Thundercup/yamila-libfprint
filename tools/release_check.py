#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Check audited public documentation links without network or host changes."""
import argparse
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

from audit import ROOT, audit


def check_links(root):
    root = root.resolve()
    checked = 0
    for document in sorted(root.rglob('*.md')):
        relative = document.relative_to(root)
        if relative.parts[0] in ('build', '.cache', '.git'):
            continue
        for target in re.findall(r'\]\(([^\s)]+)\)', document.read_text()):
            url = urlsplit(target)
            if url.scheme in ('https', 'http', 'mailto'):
                continue
            if url.scheme or url.netloc or Path(unquote(url.path)).is_absolute():
                raise ValueError('unsupported link: '+str(relative)+': '+target)
            destination = (document.parent/unquote(url.path)).resolve() if url.path else document
            if not destination.is_relative_to(root):
                raise ValueError('link escapes public source: '+str(relative)+': '+target)
            if not destination.exists():
                raise ValueError('missing link target: '+str(relative)+': '+target)
            if url.fragment:
                if destination.suffix != '.md':
                    raise ValueError('unsupported local fragment: '+target)
                text = destination.read_text()
                headings = re.findall(r'^#{1,6} (.+)$', text, re.M)
                anchors = {re.sub(r'[^\w\-\s]', '', title.lower()).replace(' ', '-')
                           for title in headings}
                anchors.update(re.findall(r'\bid=["\x27]([^"\x27]+)["\x27]', text))
                if unquote(url.fragment) not in anchors:
                    raise ValueError('missing local anchor: '+str(relative)+': '+target)
            checked += 1
    return checked


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    manifest = audit()
    count = check_links(ROOT)
    print('Public release checks OK: '+str(len(manifest['files']))+
          ' allowlisted files; '+str(count)+' local documentation links')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        sys.exit(str(error))
