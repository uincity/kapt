import pandas as pd

from .base import ParseResult


def parse_xlsx(path):
    sheets = pd.read_excel(path, sheet_name=None, header=None)
    text = '\n'.join(f'[{name}]\n{frame.to_csv(index=False, header=False)}'
                     for name, frame in sheets.items())
    return ParseResult(text, 'pandas-openpyxl', str(path))
