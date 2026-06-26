"""
access.py — translates the authenticated user's Entra ID group membership into
what they're allowed to see.

Static Web Apps injects the authenticated principal as a base64 JSON blob in the
`x-ms-client-principal` header. We read the user's roles/groups from it. No
secrets, no token validation needed here — SWA has already authenticated the
request before it reaches the Function.

Group convention (create these in Entra ID):
  Apollo-ET                 -> sees every report, all clinics
  Apollo-CD-<clinic_slug>   -> sees clinic-based reports for that one clinic
                               (e.g. Apollo-CD-grayson, Apollo-CD-dallas)

A user in multiple CD groups sees all of their clinics. A user in Apollo-ET
sees everything regardless of CD groups.
"""

import json
import base64

# ---- report catalog --------------------------------------------------------
# `scope`:
#   "all"     -> a single ET-only workbook covering every clinic (no per-clinic split)
#   "clinic"  -> one workbook per clinic; CDs see only theirs, ET sees all
#
# Layout in the `apollo-reports` container (one dated folder per run):
#   outputs/{folder}/{YYYY-MM-DD}/<the .xlsx>
# "Latest" = newest dated subfolder under outputs/{folder}/.
REPORT_CATALOG = {
    "ar": {
        "title": "Accounts Receivable",
        "scope": "all",            # change to "clinic" once you emit per-clinic AR
        "folder": "outputs/ar",
    },
    "rev": {
        "title": "Daily Revenue",
        "scope": "all",
        "folder": "outputs/revenue",   # note: folder is 'revenue', key stays 'rev'
    },
    "supervision": {
        "title": "Supervision Ratio",
        "scope": "all",
        "folder": "outputs/supervision",
    },
}

CONTAINER = "apollo-reports"
# Azure Static Web Apps role names allow only letters, numbers, underscores
# (no hyphens), so we use Apollo_ET / Apollo_CD_<clinic>.
ET_GROUP = "Apollo_ET"
CD_PREFIX = "Apollo_CD_"


def _principal_from_header(header_val: str) -> dict:
    if not header_val:
        return {}
    try:
        decoded = base64.b64decode(header_val).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return {}


def get_user(req_headers) -> dict:
    """
    Returns {"name", "groups": [...], "is_et": bool, "clinics": [...]}.
    `clinics` is the list of clinic slugs a CD can see; empty for pure ET.
    """
    principal = _principal_from_header(req_headers.get("x-ms-client-principal"))
    name = principal.get("userDetails", "")
    # SWA puts AAD groups/roles in claims; configurable. We accept either
    # explicit roles or group-object-ids surfaced as roles.
    roles = set(principal.get("userRoles", []))
    # Also accept group claims if you map them through (see staticwebapp.config.json)
    for c in principal.get("claims", []):
        if c.get("typ", "").endswith("groups") or c.get("typ") == "groups":
            roles.add(c.get("val"))

    is_et = ET_GROUP in roles
    clinics = sorted(
        r[len(CD_PREFIX):] for r in roles if r.startswith(CD_PREFIX)
    )
    return {"name": name, "groups": sorted(roles), "is_et": is_et, "clinics": clinics}


def visible_reports(user: dict) -> list:
    """List of report descriptors this user may open."""
    out = []
    for key, cfg in REPORT_CATALOG.items():
        if cfg["scope"] == "all":
            # ET-wide report: only ET (and explicitly-permitted) users
            if user["is_et"]:
                out.append({"key": key, "title": cfg["title"], "clinic": "all"})
        else:  # per-clinic report
            if user["is_et"]:
                out.append({"key": key, "title": cfg["title"], "clinic": "all"})
            for clinic in user["clinics"]:
                out.append({"key": key, "title": cfg["title"], "clinic": clinic})
    return out


def can_access(user: dict, report_key: str, clinic: str) -> bool:
    cfg = REPORT_CATALOG.get(report_key)
    if not cfg:
        return False
    if user["is_et"]:
        return True
    if cfg["scope"] == "all":
        return False  # all-clinic reports are ET-only
    return clinic in user["clinics"]


def folder_prefix(report_key: str, clinic: str = "all") -> str:
    """
    Returns the prefix under which dated run-folders live, e.g.
    'outputs/ar/'. The reader lists blobs under this prefix, finds the newest
    date, and serves the .xlsx inside it. (clinic is accepted for the phase-2
    per-clinic layout; for scope='all' reports it isn't part of the path.)
    """
    cfg = REPORT_CATALOG[report_key]
    base = cfg["folder"]
    if cfg["scope"] == "clinic" and clinic and clinic != "all":
        return f"{base}/{clinic}/"
    return f"{base}/"
