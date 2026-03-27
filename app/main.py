import asyncio
import logging
import os
import time
import traceback
from contextlib import asynccontextmanager

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.routers import dashboard, transactions, upload, categories, rules, reports, subscriptions, api, data, accounts

# ── Logging setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
# Quiet down noisy third-party libraries but keep our app at DEBUG
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
logging.getLogger("multipart").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)  # we log requests ourselves

logger = logging.getLogger(__name__)


# ── Migrations ────────────────────────────────────────────────────────────────
def run_migrations() -> None:
    logger.info("▶ Running Alembic migrations …")
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    logger.info("✔ Migrations complete")


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs("uploads", exist_ok=True)
    await asyncio.to_thread(run_migrations)
    logger.info("✔ App ready")
    yield


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Personal Finance Manager", lifespan=lifespan)


# ── Request logging middleware ────────────────────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    rid = os.urandom(3).hex()          # short request-id for correlating log lines
    start = time.perf_counter()
    content_length = request.headers.get("content-length", "-")
    content_type  = request.headers.get("content-type", "-")
    logger.info(
        "[%s] ▶ %s %s  content-length=%s  content-type=%s",
        rid, request.method, request.url.path, content_length, content_type,
    )

    try:
        response = await call_next(request)
    except Exception:
        logger.exception("[%s] ✖ unhandled error", rid)
        raise

    elapsed = (time.perf_counter() - start) * 1000
    logger.info("[%s] ◀ %s %s  status=%s  %.0fms",
                rid, request.method, request.url.path, response.status_code, elapsed)
    return response


# ── Global exception handler (returns traceback in browser) ──────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> PlainTextResponse:
    tb = traceback.format_exc()
    logger.error("✖ Unhandled exception on %s %s\n%s", request.method, request.url, tb)
    return PlainTextResponse(
        f"500 Internal Server Error\n\n{type(exc).__name__}: {exc}\n\n{tb}",
        status_code=500,
    )


app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(dashboard.router)
app.include_router(transactions.router)
app.include_router(upload.router)
app.include_router(categories.router)
app.include_router(rules.router)
app.include_router(reports.router)
app.include_router(subscriptions.router)
app.include_router(api.router)
app.include_router(data.router)
app.include_router(accounts.router)
