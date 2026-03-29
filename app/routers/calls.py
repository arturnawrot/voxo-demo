import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.database import get_session
from app.models import Call
from app.voxo_client import get_voxo_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/calls", tags=["calls"])


@router.get("")
def list_calls(session: Session = Depends(get_session)) -> list[dict]:
    calls = session.exec(select(Call).order_by(Call.start_time.desc())).all()
    return [_serialize(c) for c in calls]


@router.post("/sync")
async def sync_calls() -> dict[str, Any]:
    """
    Trigger a manual sync: fetch new call logs from Voxo and mark recorded
    calls as pending transcription.  Safe to call while the cron is running —
    the ARQ _job_id dedup prevents double transcription.
    """
    try:
        result = await asyncio.to_thread(_do_sync)
        return {"status": "ok", **result}
    except Exception as exc:
        logger.exception("Sync failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/retry-failed")
def retry_failed(session: Session = Depends(get_session)) -> dict:
    """Reset all failed transcriptions back to pending so the worker retries them."""
    calls = session.exec(select(Call).where(Call.transcription_status == "failed")).all()
    for call in calls:
        call.transcription_status = "pending"
        session.add(call)
    session.commit()
    return {"reset": len(calls)}


@router.get("/{call_id}/recording-url")
def fresh_recording_url(call_id: str, session: Session = Depends(get_session)) -> dict:
    """
    Return a freshly signed S3 URL for a call's recording.
    Signed URLs expire after 1 h so the frontend requests this on demand.
    """
    call = session.exec(select(Call).where(Call.call_id == call_id)).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    if not call.recorded:
        raise HTTPException(status_code=404, detail="No recording for this call")

    try:
        from datetime import datetime, timezone
        voxo = get_voxo_client()
        rec = voxo.v2.CallRecordingByCallId.execute(call_id=call_id)
        call.media_url = rec.mediaURL
        call.media_url_fetched_at = datetime.now(timezone.utc)
        session.add(call)
        session.commit()
        return {"url": rec.mediaURL}
    except Exception as exc:
        logger.error("Could not refresh recording URL for %s: %s", call_id, exc)
        raise HTTPException(status_code=502, detail="Could not fetch recording from Voxo")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _do_sync() -> dict:
    from app.sync import run_sync
    return run_sync()


def _serialize(call: Call) -> dict:
    return {
        "id": call.id,
        "call_id": call.call_id,
        "direction": call.direction,
        "cid_number": call.cid_number,
        "cid_name": call.cid_name,
        "dialed_number": call.dialed_number,
        "dialed_name": call.dialed_name,
        "start_time": call.start_time,
        "end_time": call.end_time,
        "answered_at": call.answered_at,
        "disposition": call.disposition,
        "recorded": bool(call.recorded),
        "recording_duration": call.recording_duration,
        "media_url": call.media_url,
        "transcription": call.transcription,
        "transcription_status": call.transcription_status,
        "fetched_at": call.fetched_at.isoformat() if call.fetched_at else None,
    }
