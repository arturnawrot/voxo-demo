import logging
import time

from nexsure_api.credentials import NoAuth, NexsureCredentials
from nexsure_api.nexsure_api_client import NexsureApiClient

from app.config import settings

logger = logging.getLogger(__name__)

_token: str | None = None
_token_expires_at: float = 0.0


def _refresh_token() -> None:
    global _token, _token_expires_at
    bootstrap = NexsureApiClient(credentials=[NoAuth()])
    resp = bootstrap.services.GetToken.execute(
        integration_key=settings.nexsure_integration_key,
        integration_login=settings.nexsure_integration_login,
        integration_pwd=settings.nexsure_integration_pwd,
    )
    _token = resp.access_token
    _token_expires_at = time.monotonic() + resp.expires_in - 60
    logger.info("Nexsure token refreshed (valid for %ds)", resp.expires_in)


def get_nexsure_client() -> NexsureApiClient:
    if _token is None or time.monotonic() >= _token_expires_at:
        _refresh_token()
    return NexsureApiClient(credentials=[
        NoAuth(),
        NexsureCredentials(api_token=_token),
    ])
