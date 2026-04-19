from fastapi import APIRouter, HTTPException

from app.schemas.reading import AskRequest, AskResponse
from app.services.ollama_client import OllamaServiceError
from app.services.paper_store import PaperStoreError
from app.services.reading_service import ReadingServiceError, ask_about_current_paper


router = APIRouter(tags=["reading"])


@router.post("/ask", response_model=AskResponse)
def ask_paper(request: AskRequest) -> AskResponse:
    try:
        return ask_about_current_paper(
            paper_id=request.paper_id,
            question=request.question,
            chat_history=request.chat_history,
            eval_mode=request.eval_mode,
        )
    except PaperStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OllamaServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ReadingServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
