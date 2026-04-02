import logging
import re

from fastapi import APIRouter
from nylas import Client

from app.cache import cache_delete_pattern, cache_get, cache_set
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/emails", tags=["emails"])

_nylas = Client(settings.nylas_api_key, settings.nylas_api_url)

_CACHE_TTL = 300  # seconds


@router.get("")
def list_emails(limit: int = 25, page_token: str | None = None) -> dict:
    cache_key = f"emails:{page_token or 'root'}:{limit}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    result = _fetch_from_nylas(limit=limit, page_token=page_token)
    cache_set(cache_key, result, ttl=_CACHE_TTL)
    return result


@router.post("/sync")
def sync_emails(limit: int = 25) -> dict:
    """Bust the cache and re-fetch the first page from Nylas."""
    cache_delete_pattern("emails:*")
    result = _fetch_from_nylas(limit=limit)
    cache_set(f"emails:root:{limit}", result, ttl=_CACHE_TTL)
    return {"status": "ok", "fetched": len(result["emails"])}


def _fetch_from_nylas(limit: int, page_token: str | None = None) -> dict:
    query_params: dict = {"limit": limit}
    if page_token:
        query_params["page_token"] = page_token

    data, _, next_cursor = _nylas.messages.list(
        settings.nylas_grant_id,
        query_params=query_params,
    )

    return {
        "emails": [_serialize(m) for m in data],
        "next_cursor": next_cursor,
    }


def _serialize(m) -> dict:
    from_list = m.from_ or []
    to_list = m.to or []

    def _name(entry):
        if isinstance(entry, dict):
            return entry.get("name", "") or entry.get("email", "")
        return getattr(entry, "name", "") or getattr(entry, "email", "")

    def _email(entry):
        if isinstance(entry, dict):
            return entry.get("email", "")
        return getattr(entry, "email", "")

    body_text = re.sub(r"<[^>]+>", " ", m.body or "").strip() if m.body else ""

    return {
        "id": m.id,
        "subject": m.subject or "(no subject)",
        "from_name": _name(from_list[0]) if from_list else "",
        "from_email": _email(from_list[0]) if from_list else "",
        "to_email": _email(to_list[0]) if to_list else "",
        "snippet": m.snippet or "",
        "body_text": body_text,
        "date": m.date,  # raw Unix timestamp — parsed client-side
        "unread": bool(m.unread),
    }
