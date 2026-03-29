"""
Entry point for the ARQ worker.

Python 3.14 no longer auto-creates an event loop, but ARQ's Worker.__init__
calls asyncio.get_event_loop() before setting one up itself.  Create and set
the loop here, before importing anything that touches ARQ internals.
"""
import asyncio
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

asyncio.set_event_loop(asyncio.new_event_loop())

from arq import run_worker  # noqa: E402
from app.worker import WorkerSettings  # noqa: E402

run_worker(WorkerSettings)
