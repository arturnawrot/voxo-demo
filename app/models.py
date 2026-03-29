from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class Call(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    # --- from Voxo CallLogRecord ---
    call_id: str = Field(unique=True, index=True)
    start_time: str
    direction: str          # IN | OUT
    end_time: str
    cid_number: str         # caller ID number
    cid_name: str           # caller ID name
    dialed_number: str
    dialed_name: str
    disposition: str        # ANSWERED | NO ANSWER | BUSY | etc.
    recorded: int = Field(default=0)
    unique_id: str
    answered_at: Optional[str] = None

    # --- from Voxo CallRecording (fetched separately for recorded=1 calls) ---
    media_url: Optional[str] = None
    media_url_fetched_at: Optional[datetime] = None
    recording_duration: Optional[int] = None   # seconds

    # --- OpenAI transcription ---
    transcription: Optional[str] = None
    # none | pending | processing | done | failed
    transcription_status: str = Field(default="none")

    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
