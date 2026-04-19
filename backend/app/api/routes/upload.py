import hashlib
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.schemas.paper import PaperRecord
from app.services.mineru_parser import MineruParseError, parse_pdf_with_mineru
from app.services.paper_store import (
    PaperStoreError,
    load_parsed_paper_cache,
    remove_parsed_paper_cache,
    restore_parsed_paper_cache_to_current_session,
    save_current_pdf,
    save_current_paper,
    save_parsed_paper_cache_from_current_session,
)
from app.services.section_router import try_prepare_section_embeddings


router = APIRouter(tags=["upload"])
logger = logging.getLogger(__name__)


@router.post("/upload", response_model=PaperRecord)
async def upload_paper(file: UploadFile = File(...)) -> PaperRecord:
    # 先做最小校验，保证上传的是 PDF。
    if not file.filename:
        raise HTTPException(status_code=400, detail="未收到文件名。")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="请上传 PDF 文件。")

    try:
        pdf_sha256 = await _compute_upload_sha256(file)
        paper_id = uuid4().hex
        original_filename = Path(file.filename).name
        cached_paper_content = load_parsed_paper_cache(pdf_sha256)

        if cached_paper_content is not None:
            try:
                restore_parsed_paper_cache_to_current_session(pdf_sha256, paper_id)
                paper_record = PaperRecord(
                    paper_id=paper_id,
                    **cached_paper_content.model_dump(),
                )
                save_current_paper(paper_record)
                try_prepare_section_embeddings(paper_record)
                logger.info("Parsed paper cache HIT for %s, MinerU skipped.", pdf_sha256)
                return paper_record
            except PaperStoreError as exc:
                remove_parsed_paper_cache(pdf_sha256)
                logger.warning(
                    "Parsed paper cache INVALID_FALLBACK for %s: restore failed, cache removed, falling back to MinerU: %s",
                    pdf_sha256,
                    exc,
                )

        logger.info("Parsed paper cache MISS for %s, running MinerU.", pdf_sha256)
        paper_content = await parse_pdf_with_mineru(file, paper_id=paper_id)
        paper_record = PaperRecord(
            paper_id=paper_id,
            **paper_content.model_dump(),
        )
        await save_current_pdf(file, paper_id)
        save_current_paper(paper_record)
        try:
            save_parsed_paper_cache_from_current_session(
                pdf_sha256=pdf_sha256,
                paper_id=paper_id,
                original_filename=original_filename,
                paper_content=paper_content,
            )
            logger.info("Parsed paper cache SAVE for %s completed.", pdf_sha256)
        except PaperStoreError as exc:
            logger.warning("Parsed paper cache SAVE_FAILED for %s: %s", pdf_sha256, exc)
        try_prepare_section_embeddings(paper_record)
        return paper_record
    except MineruParseError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except PaperStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def _compute_upload_sha256(file: UploadFile) -> str:
    """流式计算上传 PDF 的文件内容 SHA-256，并在结束后恢复文件指针。"""
    digest = hashlib.sha256()
    await file.seek(0)

    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)

    await file.seek(0)
    return digest.hexdigest()
