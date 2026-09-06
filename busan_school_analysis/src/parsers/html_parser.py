from html.parser import HTMLParser
import re

from .base import ParseResult


def clean_text(value):
    return re.sub(r'\s+', ' ', value.replace('\xa0', ' ')).strip()


class TableParser(HTMLParser):
    """Dependency-free HTML table reader with rowspan/colspan expansion."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.table, self.row, self.cell = [], None, None, None
        self.pending = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'table' and self.table is None:
            self.table, self.pending = [], {}
        elif self.table is not None and tag == 'tr':
            self.row = []
        elif self.row is not None and tag in ('td', 'th'):
            self.cell = [[], int(attrs.get('rowspan', 1)), int(attrs.get('colspan', 1))]
        elif self.cell is not None and tag == 'br':
            self.cell[0].append('\n')

    def handle_data(self, data):
        if self.cell is not None:
            self.cell[0].append(data)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            value = clean_text(''.join(self.cell[0]))
            self.row.append((value, self.cell[1], self.cell[2]))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            expanded, col = [], 0
            def consume_pending():
                nonlocal col
                while col in self.pending:
                    value, remaining = self.pending[col]
                    expanded.append(value)
                    if remaining <= 1:
                        del self.pending[col]
                    else:
                        self.pending[col] = (value, remaining - 1)
                    col += 1
            consume_pending()
            for value, rowspan, colspan in self.row:
                consume_pending()
                for _ in range(colspan):
                    expanded.append(value)
                    if rowspan > 1:
                        self.pending[col] = (value, rowspan - 1)
                    col += 1
            consume_pending()
            if any(expanded):
                self.table.append(expanded)
            self.row = None
        elif tag == 'table' and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def tables_from_html(html):
    parser = TableParser()
    parser.feed(html)
    return parser.tables


def parse_html(path):
    path = str(path)
    raw = open(path, encoding='utf-8').read()
    text = '\n'.join(' | '.join(row) for table in tables_from_html(raw) for row in table)
    return ParseResult(text=text, extraction_method='html.parser', source_path=path)
