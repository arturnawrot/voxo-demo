from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from app.routers.auth import COOKIE_NAME, verify_session_token

_EXEMPT = {"/login", "/auth/login"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in _EXEMPT:
            return await call_next(request)

        token = request.cookies.get(COOKIE_NAME)
        if token and verify_session_token(token):
            return await call_next(request)

        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return RedirectResponse(url="/login", status_code=302)
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
