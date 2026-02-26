from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.logging import get_logger
from backend.routers.analytics import router as analytics_router
from backend.db.clickhouse import execute_query
from backend.services.query_builder import build_available_patches_query

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Current patch — resolved at startup, used as default filter
# ---------------------------------------------------------------------------

current_patch: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global current_patch
    try:
        results = execute_query(build_available_patches_query())
        if results:
            current_patch = results[0]["game_version"]
            logger.info("current patch detected", patch=current_patch)
        else:
            logger.warning("no patch data found in clickhouse")
    except Exception as e:
        logger.warning("could not detect current patch", error=str(e))
    yield


app = FastAPI(
    title="TFT Analytics API",
    description="Champion and item statistics for TFT ranked games",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — allow React frontend to call the API
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(analytics_router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "current_patch": current_patch}
