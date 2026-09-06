from pathlib import Path
import re
import zipfile
from xml.etree import ElementTree

from .base import ParseResult


def parse_hwpx(path):
    path = Path(path)
    if path.read_bytes()[:8] == bytes.fromhex('D0CF11E0A1B11AE1'):
        return ParseResult('', 'unsupported_legacy_hwp', str(path), ['manual_conversion_required'])
    parts = []
    try:
        with zipfile.ZipFile(path) as archive:
            names = sorted(n for n in archive.namelist()
                           if re.search(r'Contents/section\d+\.xml$', n, re.I))
            for name in names:
                root = ElementTree.fromstring(archive.read(name))
                parts.extend(node.text for node in root.iter() if node.tag.endswith('}t') and node.text)
    except (zipfile.BadZipFile, ElementTree.ParseError):
        return ParseResult('', 'unsupported', str(path), ['invalid_hwpx'])
    return ParseResult('\n'.join(parts), 'hwpx_zip_xml', str(path))
