from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.app.dependencies import get_predictor_service


router = APIRouter(prefix="/predictions", tags=["predictions"])


@router.get("/{crossing_id}")
async def get_predictions(
    crossing_id: str,
    horizon_minutes: int = Query(default=20, ge=1, le=180),
    recent_minutes: int = Query(default=10, ge=1, le=60),
    warning_minutes: int = Query(default=5, ge=1, le=30),
) -> dict:
    predictor = get_predictor_service()
    try:
        envelope = await predictor.predict_for_crossing(
            crossing_id,
            horizon_minutes=horizon_minutes,
            recent_minutes=recent_minutes,
            warning_minutes=warning_minutes,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return envelope.model_dump(mode="json")