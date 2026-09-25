"""Two listeners, two rules, no mixing.

UI port (8080): reachable only from ingress-nginx (NetworkPolicy), and only
through the authentik-gated Ingress. ingress-nginx sets X-authentik-username
from the forward-auth response and overwrites any client-supplied copy
(auth-response-headers), so its presence means "authentik let this through".

Machine port (8081): MCP + /metrics. Bearer token only. The authentik header
means nothing here, so spoofing it gains nothing.

Starlette's HTTP middleware does not run for WebSocket connections, so the
live-view socket checks `ui_user()` itself.
"""

import hmac

from starlette.datastructures import Headers


def ui_user(headers: Headers) -> str | None:
    return headers.get("x-authentik-username") or None


def bearer_ok(headers: Headers, api_token: str) -> bool:
    supplied = headers.get("authorization", "")
    return hmac.compare_digest(supplied.encode(), f"Bearer {api_token}".encode())
