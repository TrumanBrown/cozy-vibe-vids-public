"""docs/asset-ledger.csv: where it is, and cells a spreadsheet only ever shows as text.

The ledger is opened in Excel or LibreOffice now and then, and some of its text comes from outside: track titles and
artists from music pages and catalogs, a font's copyright line. A cell that starts like a formula would run there.
"""
from cozy.paths import ROOT

LEDGER = ROOT / "docs" / "asset-ledger.csv"
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def cell(v):
    """The text, with an apostrophe in front when it starts like a formula, which spreadsheets show as text instead of
    running (OWASP's advice for CSV injection). Other text is unchanged, so rewriting a row twice changes nothing."""
    s = "" if v is None else str(v)
    return "'" + s if s.startswith(FORMULA_START) else s


def row(r):
    """cell() for every value of a list or dict row."""
    return {k: cell(v) for k, v in r.items()} if isinstance(r, dict) else [cell(v) for v in r]
