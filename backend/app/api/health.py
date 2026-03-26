from fastapi import APIRouter

from app.config import get_settings

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "reliability_features_enabled": str(settings.reliability_features_enabled).lower(),
        "safety_guard_enabled": str(settings.safety_guard_enabled).lower(),
        "safety_guard_strict_block": str(settings.safety_guard_strict_block).lower(),
    }
