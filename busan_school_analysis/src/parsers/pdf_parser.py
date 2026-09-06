from pathlib import Path
import shutil
import subprocess

from .base import ParseResult


def parse_pdf(path):
    path = Path(path)
    companion = path.with_suffix('.txt')
    if companion.exists():
        return ParseResult(companion.read_text(encoding='utf-8'), 'preserved_companion_text', str(path))
    executable = shutil.which('pdftotext')
    if executable:
        result = subprocess.run([executable, '-layout', str(path), '-'], capture_output=True,
                                timeout=60, check=False)
        if result.stdout:
            return ParseResult(result.stdout.decode('utf-8', errors='replace'),
                               'pdftotext-layout', str(path),
                               [] if result.returncode == 0 else ['pdftotext_nonzero_exit'])
    return ParseResult('', 'unsupported', str(path), ['text_extraction_unavailable'])
