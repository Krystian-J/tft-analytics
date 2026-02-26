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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analytics_router)


@app.get("/health")
def health():
    from backend.services.patch import get_current_patch
    return {"status": "ok", "current_patch": get_current_patch()}
