import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from app.config import settings
from app.database import engine
from app.models import Call
from app.voxo_client import get_tenant_id, get_voxo_client

logger = logging.getLogger(__name__)

_sync_lock = threading.Lock()


def _date_range() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=settings.sync_lookback_days)
    fmt = "%Y-%m-%dT%H:%M:%S-06:00"
    return start.strftime(fmt), now.strftime(fmt)


def run_sync() -> dict:
    """
    Fetch call logs from Voxo, persist new ones, mark recorded calls as
    pending transcription.  Idempotent — existing call_ids are skipped.
    """
    if not _sync_lock.acquire(blocking=False):
        logger.info("Sync already in progress — skipping duplicate call")
        return {"new_calls": 0, "pending_transcriptions": 0}

    try:
        return _run_sync()
    finally:
        _sync_lock.release()


def _run_sync() -> dict:
    logger.info("Sync started")
    client = get_voxo_client()
    start_date, end_date = _date_range()

    new_calls = 0
    pending_transcriptions = 0
    page = 1
    max_page = 1

    with Session(engine) as session:
        while page <= max_page:
            try:
                response = client.v2.CallLogs.execute(
                    tenant_id=get_tenant_id(),
                    start_date=start_date,
                    end_date=end_date,
                    page=page,
                    records_per_page=50,
                )
            except Exception as exc:
                logger.warning("Skipping page %d — Voxo deserialization error: %s", page, exc)
                page += 1
                continue

            max_page = response.maxPage

            for record in response.records:
                exists = session.exec(
                    select(Call).where(Call.call_id == record.callId)
                ).first()
                if exists:
                    continue

                call = Call(
                    call_id=record.callId,
                    start_time=record.startTime,
                    direction=record.direction,
                    end_time=record.endTime,
                    cid_number=record.cidNumber,
                    cid_name=record.cidName,
                    dialed_number=record.dialedNumber,
                    dialed_name=record.dialedName,
                    disposition=record.disposition,
                    recorded=record.recorded,
                    unique_id=record.uniqueId,
                    answered_at=record.answeredAt,
                )

                if record.recorded:
                    try:
                        rec = client.v2.CallRecordingByCallId.execute(call_id=record.callId)
                        call.media_url = rec.mediaURL
                        call.media_url_fetched_at = datetime.now(timezone.utc)
                        call.recording_duration = rec.duration
                        call.transcription_status = "pending"
                        pending_transcriptions += 1
                    except Exception as exc:
                        logger.warning("Could not fetch recording for %s: %s", record.callId, exc)

                session.add(call)
                new_calls += 1

            page += 1

        session.commit()

    logger.info("Sync done — %d new, %d pending transcription", new_calls, pending_transcriptions)
    return {"new_calls": new_calls, "pending_transcriptions": pending_transcriptions}
