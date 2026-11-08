"""Bounded parser diagnostics without source contents, paths, or exception messages."""
import re

PARSE_MESSAGES = {
    'parse_failed': 'The filing could not be parsed completely; previous data was preserved',
    'parse_dependency_missing': 'A required filing taxonomy or linkbase reference could not be resolved; previous data was preserved',
}


def diagnostic_codes(values):
    return sorted({str(value) for value in values if re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', str(value))})[:20]


class ParseFailure(Exception):
    def __init__(self, code, diagnostics=()):
        self.code = code
        self.diagnostics = diagnostic_codes(diagnostics)
        super().__init__(PARSE_MESSAGES[code])
