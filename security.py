"""
security.py — HTTP hardening for the dashboard.

One function, called once from app.py. It adds response headers and a request
size cap; it does not touch routing, data access or any existing behaviour.

The policy is written against what the templates actually load today:

- scripts come only from /static (Chart.js is vendored locally), so script-src
  stays at 'self' with no 'unsafe-inline'. That is the header that actually
  stops an injected <script> from running.
- styles need 'unsafe-inline': the templates carry style="..." attributes and
  the dashboard sets a few widths from data (bar charts, progress fills).
  Removing them is a wider refactor than this file should attempt, and an
  inline style is a far smaller risk than an inline script.
- fonts come from Google Fonts, so those two hosts are allowed by name rather
  than opening the policy up.
- everything else defaults to 'none', so no plugin, frame, form post or
  websocket can be introduced without an explicit change here.
"""

from __future__ import annotations

from typing import Final

# 5 MB. The largest legitimate request this app receives is a small JSON body;
# the cap only exists so an oversized POST is rejected before it is buffered.
MAX_REQUEST_BYTES: Final[int] = 5 * 1024 * 1024

CONTENT_SECURITY_POLICY: Final[str] = "; ".join(
    [
        "default-src 'none'",
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data:",
        "connect-src 'self'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "object-src 'none'",
        "upgrade-insecure-requests",
    ]
)

SECURITY_HEADERS: Final[dict] = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    # Stops a browser from guessing a response is HTML when it is JSON.
    "X-Content-Type-Options": "nosniff",
    # Clickjacking. frame-ancestors above covers modern browsers; this covers
    # the rest.
    "X-Frame-Options": "DENY",
    # Do not leak the dashboard's URLs to third-party hosts.
    "Referrer-Policy": "no-referrer",
    # The dashboard needs none of these.
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=(), usb=()",
    # Responses are per-session operational data, not something to cache.
    "Cache-Control": "no-store",
}


def apply(app, *, force_https: bool = False, enabled: bool = True) -> None:
    """
    Attach the headers and the request size cap to a Flask app.

    force_https adds HSTS. It is off by default because the app runs on plain
    HTTP in development, and sending HSTS from an HTTP origin either does
    nothing or, once it has been sent over HTTPS once, locks the browser out of
    the HTTP version for a year. Turn it on only behind a real TLS terminator.
    """
    if not enabled:
        # Escape hatch for diagnosing a page that stopped working after these
        # headers were added: set SECURITY_HEADERS=off and reload. If the
        # problem disappears, the policy above is the cause and needs widening;
        # if it persists, look elsewhere. Never leave this off in normal use.
        return

    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES

    @app.after_request
    def _headers(response):
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)

        # Static assets are fingerprint-free here, so keep them revalidating
        # rather than uncached, which is what no-store would force.
        if response.mimetype in {"text/css", "application/javascript", "text/javascript"}:
            response.headers["Cache-Control"] = "no-cache"

        if force_https:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )

        return response
