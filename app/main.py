import logging

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import create_db_and_tables
from app.middleware import AuthMiddleware
from app.routers.auth import router as auth_router
from app.routers.calls import router as calls_router
from app.routers.emails import router as emails_router
from app.routers.nexsure import router as nexsure_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Voxo Demo")
app.add_middleware(AuthMiddleware)

# ---------------------------------------------------------------------------
# startup / shutdown
# ---------------------------------------------------------------------------

scheduler = BackgroundScheduler()


@app.on_event("startup")
def on_startup() -> None:
    create_db_and_tables()

    # Cron: sync call logs every 1 minute
    scheduler.add_job(
        _sync_job,
        trigger="interval",
        minutes=1,
        id="call_sync",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started — syncing every 1 minute")


@app.on_event("shutdown")
def on_shutdown() -> None:
    scheduler.shutdown(wait=False)


def _sync_job() -> None:
    """Runs in a background thread via APScheduler."""
    try:
        from app.sync import run_sync
        run_sync()
    except Exception:
        logger.exception("Scheduled sync failed")


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------

app.include_router(auth_router)
app.include_router(calls_router)
app.include_router(emails_router)
app.include_router(nexsure_router)

# Serve the SPA last so API routes take precedence
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
