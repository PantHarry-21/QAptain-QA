from fastapi import APIRouter
from config import settings

router = APIRouter()


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
    }
