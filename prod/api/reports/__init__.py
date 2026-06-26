"""
GET /api/reports
Returns the list of reports the authenticated user is allowed to open, plus
their identity (so the UI can show 'ET view' vs a clinic name).
"""

import json
import logging
import azure.functions as func

import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from shared import access


def main(req: func.HttpRequest) -> func.HttpResponse:
    user = access.get_user(req.headers)

    # If SWA auth is configured correctly this is always populated. If empty,
    # the request wasn't authenticated — return 401 so the SPA redirects to login.
    if not user["name"]:
        return func.HttpResponse(
            json.dumps({"error": "unauthenticated"}),
            status_code=401,
            mimetype="application/json",
        )

    payload = {
        "user": {
            "name": user["name"],
            "isET": user["is_et"],
            "clinics": user["clinics"],
        },
        "reports": access.visible_reports(user),
    }
    return func.HttpResponse(
        json.dumps(payload),
        mimetype="application/json",
        headers={"Cache-Control": "no-store"},
    )
