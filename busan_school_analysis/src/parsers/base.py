from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class ParseResult:
    text: str
    extraction_method: str
    source_path: str
    warnings: list[str] = field(default_factory=list)


class DocumentParser(Protocol):
    def parse(self, path: Path) -> ParseResult: ...
