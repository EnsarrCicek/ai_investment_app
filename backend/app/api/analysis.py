from fastapi import APIRouter, HTTPException

from app.engines.macro.engine import MacroAnalysisEngine
from app.engines.technical.engine import TechnicalAnalysisEngine

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/{symbol}/technical")
def get_technical_analysis(symbol: str):
    try:
        return TechnicalAnalysisEngine().analyze(symbol.upper())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/macro")
def get_macro_analysis():
    try:
        snapshot, _doc_id = MacroAnalysisEngine().analyze()
        return snapshot
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
