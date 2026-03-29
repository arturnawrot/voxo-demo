"""
ARQ worker.

Responsibilities:
  1. cron every 30 s — pick_up_pending_transcriptions
     Finds all calls with transcription_status='pending', enqueues a
     transcribe_call job per call using a stable _job_id so ARQ itself
     prevents duplicate enqueuing while the job is queued or running.

  2. transcribe_call(call_id)
     - Re-fetches a fresh recording URL from Voxo (signed S3 URLs expire
       in 1 h, so we always refresh before downloading).
     - Downloads the MP3 with httpx.
     - Transcribes with OpenAI gpt-4o-transcribe.
     - Persists the transcript and marks status='done'.
     - On any failure: status='failed'.
"""

import logging
from datetime import datetime, timezone

import httpx
from arq import cron
from arq.connections import RedisSettings
from openai import AsyncOpenAI
from sqlmodel import Session, select

from app.config import settings
from app.database import engine
from app.models import Call

logger = logging.getLogger(__name__)

openai_client = AsyncOpenAI(api_key=settings.openai_api_key)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _set_status(call_id: str, status: str, transcription: str | None = None) -> None:
    with Session(engine) as session:
        call = session.exec(select(Call).where(Call.call_id == call_id)).first()
        if call:
            call.transcription_status = status
            if transcription is not None:
                call.transcription = transcription
            session.add(call)
            session.commit()


# ---------------------------------------------------------------------------
# job
# ---------------------------------------------------------------------------

async def transcribe_call(_ctx: dict, call_id: str) -> None:
    """Download the MP3 for *call_id* and transcribe it with GPT-4o."""

    # --- guard: already done? ---
    with Session(engine) as session:
        call = session.exec(select(Call).where(Call.call_id == call_id)).first()
        if not call:
            logger.error("transcribe_call: call %s not found", call_id)
            return
        if call.transcription_status == "done":
            return
        call.transcription_status = "processing"
        session.add(call)
        session.commit()

    # --- always fetch a fresh recording URL (signed S3 URLs expire in 1 h) ---
    media_url: str | None = None
    try:
        from app.voxo_client import get_voxo_client
        voxo = get_voxo_client()
        rec = voxo.v2.CallRecordingByCallId.execute(call_id=call_id)
        media_url = rec.mediaURL

        with Session(engine) as session:
            call = session.exec(select(Call).where(Call.call_id == call_id)).first()
            if call:
                call.media_url = media_url
                call.media_url_fetched_at = datetime.now(timezone.utc)
                call.recording_duration = rec.duration
                session.add(call)
                session.commit()
    except Exception as exc:
        logger.error("Cannot fetch recording URL for %s: %s", call_id, exc)
        _set_status(call_id, "failed")
        return

    # --- download + transcribe ---
    try:
        async with httpx.AsyncClient(timeout=120) as http:
            resp = await http.get(media_url)
            resp.raise_for_status()
            audio_bytes = resp.content

        transcript = await openai_client.audio.transcriptions.create(
            model="gpt-4o-transcribe",
            file=("audio.mp3", audio_bytes, "audio/mpeg"),
        )

        _set_status(call_id, "done", transcription=transcript.text)
        logger.info("Transcription done for call %s", call_id)

    except Exception:
        logger.exception("Transcription failed for call %s", call_id)
        _set_status(call_id, "failed")


# ---------------------------------------------------------------------------
# cron — picks up pending transcription jobs
# ---------------------------------------------------------------------------

async def pick_up_pending_transcriptions(ctx: dict) -> None:
    """
    Find all calls with transcription_status='pending' and enqueue them.
    ARQ deduplicates by _job_id so this is safe to run frequently — a job
    already in the queue or running will not be re-enqueued.
    """
    with Session(engine) as session:
        pending = session.exec(
            select(Call).where(Call.transcription_status == "pending")
        ).all()

    if not pending:
        return

    enqueued = 0
    for call in pending:
        job_id = f"transcribe:{call.call_id}"
        job = await ctx["redis"].enqueue_job("transcribe_call", call.call_id, _job_id=job_id)
        if job is not None:
            enqueued += 1
            logger.debug("Enqueued transcription for %s", call.call_id)
        else:
            logger.debug("Already queued, skipping %s", call.call_id)

    if enqueued:
        logger.info("Enqueued %d transcription job(s)", enqueued)


# ---------------------------------------------------------------------------
# worker settings
# ---------------------------------------------------------------------------

class WorkerSettings:
    redis_settings = RedisSettings(host=settings.redis_host, port=settings.redis_port)
    functions = [transcribe_call]
    cron_jobs = [
        cron(pick_up_pending_transcriptions, second={0, 30}),  # every 30 s
    ]
    max_jobs = 5          # max concurrent transcriptions
    job_timeout = 300     # 5 min max per job
    keep_result = 3600    # keep job result in Redis for 1 h
