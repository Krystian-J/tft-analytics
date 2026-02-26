from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.logging import get_logger
from backend.routers.analytics import router as analytics_router

logger = get_logger(__name__)

app = FastAPI(
    title="TFT Analytics API",
    description="Champion and item statistics for TFT ranked games",
    version="1.0.0",
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
    return {"status": "ok"}


@app.on_event("startup")
async def startup():
    logger.info("TFT Analytics backend starting up")
