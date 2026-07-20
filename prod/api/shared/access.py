"""
access.py — translates the authenticated user's Entra ID role(s) into what they
can see.

Static Web Apps injects the authenticated principal as a base64 JSON blob in the
`x-ms-client-principal` header. We read the user's roles from it. No secrets, no
token validation needed here — SWA authenticates the request before it reaches
the Function.

==============================================================================
HOW ACCESS IS DEFINED  (this is the part you edit to add/adjust groups)
==============================================================================
Every group is one entry in GROUPS below. A group declares:
  - reports:  the set of report keys it may open
              (or the sentinel ALL_REPORTS to mean "every report")
  - clinic_scoped: if True, users of this group only see THEIR OWN clinic's
              rows within a report (row-level filtering; used by clinic views).
              Their clinic(s) come from apollo_cd_<clinic> style roles.
              (Row filtering itself is implemented in the report endpoint;
               this flag is what turns it on.)

Invite users to the exact lowercase role name (the dict key), e.g. apollo_et.

Examples of future edits:
  - Let RCM also see Supervision:   add "supervision" to the rcm reports set.
  - New "Clinical" group for Supervision only:
        "apollo_clinical": {"reports": {"supervision"}, "clinic_scoped": False}
  - A clinic view (Supervision only, own clinic rows):
        handled by the apollo_cd_<clinic> pattern + CLINIC_VIEW below.
==============================================================================
"""

import json
import base64

# ---- report catalog --------------------------------------------------------
REPORT_CATALOG = {
    "ar":          {"title": "Accounts Receivable", "scope": "all", "folder": "outputs/ar"},
    "rev":         {"title": "Daily Revenue",       "scope": "all", "folder": "outputs/revenue"},
    "supervision": {"title": "Supervision Ratio",   "scope": "all", "folder": "outputs/supervision"},
    "bcba":        {"title": "BCBA Billing",        "scope": "all", "folder": "outputs/bcba-billing"},
}

CONTAINER = "apollo-reports"

# Sentinel meaning "every report in the catalog".
ALL_REPORTS = "__ALL__"

# ---- GROUP DEFINITIONS (edit here to add/adjust access) --------------------
GROUPS = {
    # Executive Team: sees everything. The default superuser group.
    "apollo_et": {
        "reports": ALL_REPORTS,
        "clinic_scoped": False,
    },
    # Revenue Cycle Management: only these reports today.
    # To grant more later, add keys to this set (e.g. add "supervision").
    "apollo_rcm": {
        "reports": {"ar", "rev"},
        "clinic_scoped": False,
    },
}

# ---- Clinic views (phase 2: row-level filtering) ---------------------------
# Users invited as apollo_cd_<clinic> get a clinic-scoped view.
# CLINIC_VIEW says: which reports a clinic user may open, and that they only see
# their own clinic's rows. Revenue & AR are intentionally excluded.
CD_PREFIX = "apollo_cd_"
CLINIC_VIEW = {
    "reports": {"supervision"},   # clinic users see Supervision only
    "clinic_scoped": True,        # and only their own clinic's rows
}


def _principal_from_header(header_val: str) -> dict:
    if not header_val:
        return {}
    try:
        return json.loads(base64.b64decode(header_val).decode("utf-8"))
    except Exception:
        return {}


def get_user(req_headers) -> dict:
    """
    Returns:
      name, roles[], groups[] (recognized group role names),
      clinics[] (from apollo_cd_<clinic> roles),
      is_et (bool), reports (resolved set of allowed keys or ALL_REPORTS),
      clinic_scoped (bool)
    """
    principal = _principal_from_header(req_headers.get("x-ms-client-principal"))
    name = principal.get("userDetails", "")
    roles = set(principal.get("userRoles", []))
    for c in principal.get("claims", []):
        if c.get("typ", "").endswith("groups") or c.get("typ") == "groups":
            roles.add(c.get("val"))

    is_et = "apollo_et" in roles
    clinics = sorted(r[len(CD_PREFIX):] for r in roles if r.startswith(CD_PREFIX))

    # Resolve the union of everything this user's groups allow.
    allowed = set()
    clinic_scoped = False
    grants_all = False

    for role in roles:
        g = GROUPS.get(role)
        if g:
            if g["reports"] == ALL_REPORTS:
                grants_all = True
            else:
                allowed |= set(g["reports"])
            clinic_scoped = clinic_scoped or g["clinic_scoped"]

    if clinics:  # any apollo_cd_<clinic> role grants the clinic view
        allowed |= set(CLINIC_VIEW["reports"])
        clinic_scoped = clinic_scoped or CLINIC_VIEW["clinic_scoped"]

    reports = ALL_REPORTS if grants_all else allowed

    # ET is never clinic-scoped (sees full data).
    if grants_all:
        clinic_scoped = False

    return {
        "name": name,
        "roles": sorted(roles),
        "is_et": is_et,
        "clinics": clinics,
        "reports": reports,
        "clinic_scoped": clinic_scoped,
    }


def _may_open(user: dict, key: str) -> bool:
    if user["reports"] == ALL_REPORTS:
        return True
    return key in user["reports"]


def visible_reports(user: dict) -> list:
    out = []
    for key, cfg in REPORT_CATALOG.items():
        if _may_open(user, key):
            out.append({"key": key, "title": cfg["title"], "clinic": "all"})
    return out


def can_access(user: dict, report_key: str, clinic: str = "all") -> bool:
    if report_key not in REPORT_CATALOG:
        return False
    return _may_open(user, report_key)


def folder_prefix(report_key: str, clinic: str = "all") -> str:
    cfg = REPORT_CATALOG[report_key]
    base = cfg["folder"]
    if cfg["scope"] == "clinic" and clinic and clinic != "all":
        return f"{base}/{clinic}/"
    return f"{base}/"
