import logging
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.cache import cache_delete_pattern, cache_get, cache_set
from app.nexsure_client import get_nexsure_client
from nexsure_api.input_models import AddressInput, AssignmentInput, ContactInput
from nexsure_api.types import ClientStage, ClientType, LegalEntity, PolicyMode, PolicyStage, PolicyType, SearchType

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/nexsure", tags=["nexsure"])

_CACHE_TTL = 300  # seconds


# ---------------------------------------------------------------------------
# DTOs — dataclasses that represent the internal shape of API results
# ---------------------------------------------------------------------------

@dataclass
class NexsureClientDTO:
    client_id: str
    name: str
    client_type: str
    stage: str
    city: str
    state: str


@dataclass
class NexsureSicNaicsDTO:
    code_id: str
    naics_code: str
    naics_description: str
    sic_code: str
    sic_description: str


@dataclass
class NexsurePolicyDTO:
    policy_id: int | None
    client_id: int | None
    policy_number: str
    eff_date: str
    exp_date: str
    mode: str
    stage: str
    status: str
    description: str


# ---------------------------------------------------------------------------
# Request models — Pydantic for FastAPI body validation
# ---------------------------------------------------------------------------

class CreateClientBody(BaseModel):
    name: str
    branch_id: str
    department_id: str
    street: str
    city: str
    state: str
    zip_code: str
    client_type: str = "Commercial"
    stage: str = "Prospect"
    legal_entity: str = "Corporation"
    contact_first_name: str = ""
    contact_last_name: str = ""


class CreatePolicyBody(BaseModel):
    client_id: str
    policy_number: str
    branch_id: str
    department_id: str
    eff_date: str   # YYYY-MM-DD
    exp_date: str   # YYYY-MM-DD
    description: str = ""
    mode: str = "New"
    stage: str = "Marketing"
    policy_type: str = "Monoline"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

_MIN_SEARCH_LEN = 2


@router.get("/clients")
def list_clients(search: str = "", page: int = 1, page_size: int = 25) -> dict:
    if len(search) < _MIN_SEARCH_LEN:
        return {"clients": [], "total": 0, "page": 1, "page_size": page_size,
                "total_pages": 1, "hint": "Enter at least 2 characters to search."}

    cache_key = f"nexsure:clients:{search}:all"
    cached = cache_get(cache_key)

    if cached is None:
        all_clients = _fetch_all_clients(search)
        cached = {"clients": all_clients}
        cache_set(cache_key, cached, ttl=_CACHE_TTL)

    all_clients: list[dict] = cached["clients"]
    total = len(all_clients)
    offset = (page - 1) * page_size
    return {
        "clients": all_clients[offset: offset + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),
    }


@router.post("/clients/sync")
def sync_clients() -> dict:
    """Bust the entire Nexsure client cache (no re-prime — search is required)."""
    cache_delete_pattern("nexsure:clients:*")
    return {"status": "ok"}


@router.post("/clients")
def add_client(body: CreateClientBody) -> dict:
    """Create a new Nexsure client, then purge the client cache."""
    try:
        client = get_nexsure_client()
        assignment = AssignmentInput(
            branch_id=body.branch_id,
            department_id=body.department_id,
            is_primary=True,
        )
        contacts = None
        if body.contact_first_name or body.contact_last_name:
            contacts = [ContactInput(
                first_name=body.contact_first_name,
                last_name=body.contact_last_name,
                is_primary=True,
            )]
        address = AddressInput(
            street=body.street,
            city=body.city,
            state=body.state,
            zip_code=body.zip_code,
        )
        resp = client.services.AddNewClient.execute(
            name=body.name,
            assignment=assignment,
            client_type=ClientType(body.client_type),
            stage=ClientStage(body.stage),
            legal_entity=LegalEntity(body.legal_entity),
            contacts=contacts,
            addresses=[address],
        )
    except Exception as exc:
        logger.exception("AddNewClient failed")
        raise HTTPException(status_code=502, detail=str(exc))

    cache_delete_pattern("nexsure:clients:*")
    return {
        "status": "ok",
        "client_id": resp.Client.ClientID if resp.Client else None,
    }


@router.post("/policies")
def add_policy(body: CreatePolicyBody) -> dict:
    """Create a new Nexsure policy for an existing client, then purge the client cache."""
    try:
        client = get_nexsure_client()
        assignment = AssignmentInput(
            branch_id=body.branch_id,
            department_id=body.department_id,
            is_primary=True,
        )
        resp = client.services.AddSinglePolicy.execute(
            client_id=body.client_id,
            policy_number=body.policy_number,
            assignment=assignment,
            eff_date=body.eff_date,
            exp_date=body.exp_date,
            description=body.description,
            mode=PolicyMode(body.mode),
            stage=PolicyStage(body.stage),
            policy_type=PolicyType(body.policy_type),
        )
    except Exception as exc:
        logger.exception("AddSinglePolicy failed")
        raise HTTPException(status_code=502, detail=str(exc))

    cache_delete_pattern("nexsure:clients:*")
    return {
        "status": "ok",
        "policy_id": resp.Policy.PolicyID if resp.Policy else None,
    }


@router.get("/sic-naics")
def search_sic_naics(
    naics_description: str = "",
    sic_description: str = "",
    naics_code: str = "",
    sic_code: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    cache_key = (
        f"nexsure:sic:{naics_description}:{sic_description}"
        f":{naics_code}:{sic_code}:{page}:{page_size}"
    )
    cached = cache_get(cache_key)
    if cached is None:
        cached = _fetch_sic_naics(
            naics_description=naics_description,
            sic_description=sic_description,
            naics_code=naics_code,
            sic_code=sic_code,
            page=page,
            page_size=page_size,
        )
        cache_set(cache_key, cached, ttl=_CACHE_TTL)
    return cached


@router.post("/sic-naics/sync")
def sync_sic_naics() -> dict:
    cache_delete_pattern("nexsure:sic:*")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_all_clients(search: str) -> list[dict]:
    try:
        api = get_nexsure_client()
        resp = api.services.GetClientList.execute(client_name=search)
        return [_serialize_client(c) for c in resp.clients]
    except Exception as exc:
        logger.exception("GetClientList failed")
        raise HTTPException(status_code=502, detail=str(exc))


def _fetch_sic_naics(
    naics_description: str,
    sic_description: str,
    naics_code: str,
    sic_code: str,
    page: int,
    page_size: int,
) -> dict:
    try:
        api = get_nexsure_client()
        resp = api.services.SicNaicsSearch.execute(
            naics_description=naics_description,
            sic_description=sic_description,
            naics_code=naics_code,
            sic_code=sic_code,
            search_type=SearchType.Contains,
            page=page,
            results_per_page=page_size,
        )
        return {
            "codes": [_serialize_sic_naics(c) for c in resp.codes],
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, resp.total_pages),
        }
    except Exception as exc:
        logger.exception("SicNaicsSearch failed")
        raise HTTPException(status_code=502, detail=str(exc))


def _serialize_sic_naics(c) -> dict:
    dto = NexsureSicNaicsDTO(
        code_id=c.CodeID or "",
        naics_code=c.NaicsCode or "",
        naics_description=c.NaicsDescription or "",
        sic_code=c.SicCode or "",
        sic_description=c.SicDescription or "",
    )
    return {
        "code_id": dto.code_id,
        "naics_code": dto.naics_code,
        "naics_description": dto.naics_description,
        "sic_code": dto.sic_code,
        "sic_description": dto.sic_description,
    }


def _serialize_client(c) -> dict:
    dto = NexsureClientDTO(
        client_id=c.ClientId or "",
        name=c.ClientName or "",
        client_type=c.ClientType or "",
        stage=c.ClientStage or "",
        city=c.LocCity or "",
        state=c.LocState or "",
    )
    return {
        "client_id": dto.client_id,
        "name": dto.name,
        "client_type": dto.client_type,
        "stage": dto.stage,
        "city": dto.city,
        "state": dto.state,
    }
