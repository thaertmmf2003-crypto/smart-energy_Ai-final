"""
api_guard.py — one gate in front of every JSON endpoint.

Why this exists
---------------
page_routes.py puts @login_required on each page, so the dashboard asks for a
sign-in. The JSON API had no such guard, which left the approval gate open:

    curl -X POST https://<host>/api/agent/approve

answered 200 to anyone, signed in or not. The human approval step is the
project's central claim, so an API that executes it without a user undoes it.

Two things made the per-endpoint fix the wrong one. login_required redirects to
the login page, which a fetch() call cannot follow usefully — it needs a 401 and
JSON. And decorating twenty endpoints means the twenty-first is unprotected the
day someone adds it. A before_request hook closes both: it runs for every
request, and a new endpoint is protected the moment it exists.

The allowlist is deliberately short. Everything not named here needs a session.
"""

from __future__ import annotations

from typing import Callable, Iterable, Optional

from flask import jsonify, request

# Reachable without a session:
#   /api/health   platform health checks run before anyone signs in, and it
#                 reports only which subsystems loaded — no operational data.
PUBLIC_API_PATHS = {"/api/health"}

# Prefixes the guard ignores entirely: the sign-in flow itself, and static
# files, which Flask serves outside the /api/ namespace anyway.
PUBLIC_PREFIXES = ("/auth/", "/static/")


def apply(
    app,
    current_user: Callable[[], Optional[dict]],
    *,
    public_paths: Optional[Iterable[str]] = None,
) -> None:
    """
    Require a signed-in user for every /api/ request except the allowlist.

    current_user is auth.get_current_user, passed in rather than imported so
    this module does not depend on the auth implementation.
    """
    allowed = set(PUBLIC_API_PATHS)
    if public_paths:
        allowed.update(public_paths)

    @app.before_request
    def _require_session_for_api():
        path = request.path

        if not path.startswith("/api/"):
            return None
        if path in allowed or path.rstrip("/") in allowed:
            return None
        if path.startswith(PUBLIC_PREFIXES):
            return None

        # CORS preflight carries no cookies by design; answering it is safe
        # because the real request that follows is checked.
        if request.method == "OPTIONS":
            return None

        if current_user():
            return None

        return (
            jsonify(
                {
                    "success": False,
                    "error": "Sign in to use this endpoint.",
                    "code": "authentication_required",
                }
            ),
            401,
        )
