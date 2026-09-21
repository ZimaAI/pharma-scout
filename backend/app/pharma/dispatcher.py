"""Route only the dedicated Pharma namespace before the general-chat middleware.

Pharma has its own mandatory session/CSRF/workspace boundary. All other routes
retain the existing Gateway stack; authentication is never globally exempted.
"""

from starlette.types import ASGIApp, Receive, Scope, Send


class PharmaDispatcher:
    def __init__(self, app: ASGIApp):
        self.app = app
        self.pharma = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http" and scope.get("path", "").startswith("/api/pharma/"):
            if self.pharma is None:
                from .main import app

                self.pharma = app
            return await self.pharma(scope, receive, send)
        return await self.app(scope, receive, send)
