"""
GET /api/report/{key}/{clinic}            -> parsed JSON for the viewer
GET /api/report/{key}/{clinic}?format=xlsx -> raw .xlsx download (original bytes)

Access is enforced against the caller's Entra ID groups before any blob is read.
"""

import os
import sys
import re
import json
import logging
import azure.functions as func
from azure.storage.blob import BlobServiceClient

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from shared import access
from shared import xlsx_parser

# Connection string set in app settings (local.settings.json for dev).
# Using a connection string keeps setup simple; swap for Managed Identity +
# DefaultAzureCredential in a hardened deployment (notes in DEPLOY.md).
_CONN = os.environ.get("REPORTS_STORAGE_CONNECTION", "")
_CONTAINER = os.environ.get("REPORTS_CONTAINER", access.CONTAINER)

_DATE_RE = re.compile(r"/(\d{4}-\d{2}-\d{2})/")


def _find_latest_xlsx(container_client, prefix: str):
    """
    List blobs under e.g. 'outputs/ar/', group by the YYYY-MM-DD folder in the
    path, and return (blob_name, date_str) for the .xlsx in the newest folder.
    Returns (None, None) if nothing is found.
    """
    best_date = None
    best_blob = None
    for b in container_client.list_blobs(name_starts_with=prefix):
        if not b.name.lower().endswith(".xlsx"):
            continue
        m = _DATE_RE.search("/" + b.name)
        # date may be a path segment; fall back to last_modified if absent
        date_key = m.group(1) if m else None
        if date_key is None:
            # use last_modified as a tiebreaker key
            date_key = b.last_modified.strftime("%Y-%m-%d") if b.last_modified else "0000-00-00"
        if best_date is None or date_key > best_date:
            best_date = date_key
            best_blob = b.name
    return best_blob, best_date


def main(req: func.HttpRequest) -> func.HttpResponse:
    user = access.get_user(req.headers)
    if not user["name"]:
        return func.HttpResponse(
            json.dumps({"error": "unauthenticated"}), status_code=401,
            mimetype="application/json")

    key = req.route_params.get("key")
    clinic = req.route_params.get("clinic", "all")
    fmt = (req.params.get("format") or "json").lower()

    if not access.can_access(user, key, clinic):
        return func.HttpResponse(
            json.dumps({"error": "forbidden"}), status_code=403,
            mimetype="application/json")

    prefix = access.folder_prefix(key, clinic)
    svc = BlobServiceClient.from_connection_string(_CONN)
    container = svc.get_container_client(_CONTAINER)

    try:
        blob_name, asof = _find_latest_xlsx(container, prefix)
    except Exception:
        logging.exception("listing failed for %s", prefix)
        return func.HttpResponse(
            json.dumps({"error": "storage_error", "prefix": prefix}),
            status_code=502, mimetype="application/json")

    if not blob_name:
        return func.HttpResponse(
            json.dumps({"error": "report_not_found", "prefix": prefix}),
            status_code=404, mimetype="application/json")

    data = container.get_blob_client(blob_name).download_blob().readall()

    if fmt == "xlsx":
        fname = blob_name.split("/")[-1]
        return func.HttpResponse(
            body=data,
            status_code=200,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    # default: parsed JSON for the viewer
    meta = {
        "title": access.REPORT_CATALOG[key]["title"],
        "key": key,
        "clinic": clinic,
        "asof": asof,
        "file": blob_name.split("/")[-1],
    }
    parsed = xlsx_parser.parse_workbook(data, meta=meta)
    return func.HttpResponse(
        json.dumps(parsed, default=str),
        mimetype="application/json",
        headers={"Cache-Control": "no-store"},
    )
