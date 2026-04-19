from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.services.equation_image_service import EquationImageError, get_or_create_equation_image
from app.services.paper_store import PaperStoreError


router = APIRouter(tags=["equation"])


@router.get("/equation-image/{paper_id}/{equation_id}.png")
def equation_image(paper_id: str, equation_id: str) -> FileResponse:
    try:
        image_path = get_or_create_equation_image(paper_id, equation_id)
        return FileResponse(image_path, media_type="image/png")
    except PaperStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EquationImageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
