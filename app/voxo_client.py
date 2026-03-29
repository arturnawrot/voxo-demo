from functools import lru_cache

from voxo_api.credentials import CredentialsV2, NoAuth
from voxo_api.voxo_api_client import VoxoApiClient

from app.config import settings


@lru_cache(maxsize=1)
def get_tenant_id() -> int:
    """
    Resolve tenant ID from the configured API token via v2/authentication/jwt.
    Cached for the process lifetime — called once on first sync.
    """
    client = VoxoApiClient(credentials=[NoAuth()])
    auth = client.v2.AuthenticateAccessToken.execute(
        access_token=settings.voxo_api_token,
    )
    return auth.user.tenantId


def get_voxo_client() -> VoxoApiClient:
    """Return a VoxoApiClient authenticated with the configured v2 token."""
    client = VoxoApiClient(credentials=[NoAuth()])
    client.add_credentials(CredentialsV2(settings.voxo_api_token))
    return client
