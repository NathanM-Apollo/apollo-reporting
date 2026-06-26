"""
xlsx_parser.py — converts an Apollo report workbook into the JSON shape the
web viewer consumes: { sheets: [{name, rows}], charts: [...], meta: {...} }.

This is the single source of truth for parsing. Both the reader Function and any
local tooling import from here so the web viewer never drifts from the files.

Dependencies: openpyxl (already used by your report-generation Function).
"""

import io
import re
import glob
import os
import zipfile
import datetime
import xml.etree.ElementTree as ET
from typing import Optional

# openpyxl is used for cell values; raw zip/XML parsing is used for chart specs
import openpyxl

# ----------------------------------------------------------------------------
# Cell-value extraction
# ----------------------------------------------------------------------------

def _sheet_to_rows(ws):
    """Return a trimmed 2-D list of cell values, dates as ISO strings."""
    rows = []
    for r in ws.iter_rows():
        row = []
        for c in r:
            v = c.value
            if isinstance(v, (datetime.datetime, datetime.date)):
                v = v.isoformat()
            row.append(v)
        while row and row[-1] is None:
            row.pop()
        rows.append(row)
    while rows and not any(x is not None for x in rows[-1]):
        rows.pop()
    return rows


# ----------------------------------------------------------------------------
# Chart-spec extraction (reads the workbook's native chart XML)
# ----------------------------------------------------------------------------

_C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _txt(e):
    return "".join(t.text or "" for t in e.iter(_A + "t"))


def _parse_ref(ref):
    """'Sheet'!$B$6:$B$15 -> ('Sheet', 'B6:B15')"""
    sheet = ref.split("!")[0].strip("'")
    rng = ref.split("!")[1].replace("$", "")
    return sheet, rng


def _extract_charts_from_bytes(xlsx_bytes: bytes):
    """Pull every chart's type/title/series ranges straight from the .xlsx zip."""
    charts = []
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as z:
        chart_files = sorted(
            [n for n in z.namelist() if re.match(r"xl/charts/chart\d+\.xml$", n)],
            key=lambda p: int("".join(filter(str.isdigit, os.path.basename(p)))),
        )
        for cf in chart_files:
            root = ET.fromstring(z.read(cf))
            types = [
                el.tag.split("}")[-1]
                for el in root.iter()
                if el.tag.split("}")[-1].endswith("Chart")
                and el.tag.split("}")[-1] != "chart"
            ]
            ctype = types[0] if types else "barChart"

            grouping = None
            for g in root.iter(_C + "grouping"):
                grouping = g.get("val")
                break

            title = ""
            for tt in root.iter(_C + "title"):
                title = _txt(tt)
                break

            series = []
            sheet_name = None
            cat_sheet = None
            cat_range = None
            for ser in root.iter(_C + "ser"):
                # series name
                name = ""
                tx = ser.find(".//" + _C + "tx")
                if tx is not None:
                    vpts = [p.text for p in tx.iter(_C + "v")]
                    if vpts:
                        name = vpts[0]
                # value range
                valf = None
                for vt in ("val", "yVal"):
                    v = ser.find(".//" + _C + vt + "//" + _C + "f")
                    if v is not None:
                        valf = v.text
                        break
                # category range (taken from first series)
                catf = ser.find(".//" + _C + "cat//" + _C + "f")
                if valf:
                    s_sheet, s_rng = _parse_ref(valf)
                    sheet_name = sheet_name or s_sheet
                    if catf is not None and cat_range is None:
                        cat_sheet, cat_range = _parse_ref(catf.text)
                    series.append({"name": name, "range": s_rng})

            if series and sheet_name:
                charts.append({
                    "title": title,
                    "type": ctype,                         # barChart | lineChart
                    "grouping": grouping or "standard",    # stacked|percentStacked|standard
                    "sheet": sheet_name,
                    "catSheet": cat_sheet or sheet_name,
                    "catRange": cat_range,
                    "series": series,
                })
    return charts


# ----------------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------------

def parse_workbook(xlsx_bytes: bytes, meta: Optional[dict] = None) -> dict:
    """
    Convert raw .xlsx bytes into the viewer JSON payload.

    meta: optional dict merged into the output, e.g.
          {"title": "Accounts Receivable", "asof": "2026-06-22",
           "generated": "2026-06-22T07:45:54", "file": "Apollo_AR_Report.xlsx"}
    """
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    sheets = [{"name": ws.title, "rows": _sheet_to_rows(ws)} for ws in wb.worksheets]
    wb.close()

    charts = _extract_charts_from_bytes(xlsx_bytes)

    return {
        "sheets": sheets,
        "charts": charts,
        "meta": meta or {},
    }
