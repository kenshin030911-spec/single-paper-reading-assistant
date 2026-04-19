from fastapi import APIRouter, HTTPException

from app.schemas.reading import AnalyzeRequest, PaperAnalysisResponse
from app.services.ollama_client import OllamaServiceError
from app.services.paper_store import PaperStoreError
from app.services.reading_service import ReadingServiceError, analyze_current_paper


router = APIRouter(tags=["reading"])


@router.post("/analyze", response_model=PaperAnalysisResponse)
def analyze_paper(request: AnalyzeRequest) -> PaperAnalysisResponse:
    try:
        return analyze_current_paper(request.paper_id)
    except PaperStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OllamaServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ReadingServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
