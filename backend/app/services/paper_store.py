import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from pydantic import BaseModel, Field, ValidationError

from app.schemas.paper import PaperContent, PaperRecord
from app.schemas.reading import PaperAnalysisResponse


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CURRENT_PAPER_PATH = DATA_DIR / "current_paper.json"
CURRENT_ANALYSIS_PATH = DATA_DIR / "current_analysis.json"
CURRENT_SECTION_EMBEDDINGS_PATH = DATA_DIR / "current_section_embeddings.json"
PAPER_CACHE_DIR = DATA_DIR / "papers"
EQUATION_CACHE_DIR = DATA_DIR / "equations"
MINERU_ASSET_DIR = DATA_DIR / "mineru_assets"
PARSE_CACHE_DIR = DATA_DIR / "parse_cache"
ANALYSIS_CACHE_VERSION = 2
SECTION_EMBEDDINGS_CACHE_VERSION = 1
PARSED_PAPER_CACHE_VERSION = 1

logger = logging.getLogger(__name__)


class PaperStoreError(RuntimeError):
    """本地论文缓存读写失败时抛出的统一异常。"""


class SectionEmbeddingItem(BaseModel):
    section_index: int = Field(..., ge=0, description="章节索引")
    heading: str = Field(..., description="章节标题")
    embedding: list[float] = Field(default_factory=list, description="章节向量")


class SectionEmbeddingsCache(BaseModel):
    cache_version: int = Field(..., description="embeddings 缓存版本")
    paper_id: str = Field(..., description="当前论文 ID")
    model: str = Field(..., description="使用的 embedding 模型")
    sections: list[SectionEmbeddingItem] = Field(default_factory=list, description="章节向量列表")


class ParsedPaperCacheMeta(BaseModel):
    cache_version: int = Field(..., description="解析缓存版本")
    pdf_sha256: str = Field(..., description="PDF 文件内容 SHA-256")
    original_filename: str = Field(..., description="原始上传文件名")
    saved_at: str = Field(..., description="缓存落盘时间")


def save_current_paper(paper: PaperRecord) -> None:
    """保存当前论文缓存。上传新论文时，旧分析缓存也一并清空。"""
    _ensure_data_dir()
    _write_json(CURRENT_PAPER_PATH, paper.model_dump())
    clear_current_analysis()
    clear_current_section_embeddings()
    clear_equation_cache()


def load_current_paper(expected_paper_id: str | None = None) -> PaperRecord:
    """读取当前论文缓存，并在需要时校验 paper_id。"""
    if not CURRENT_PAPER_PATH.exists():
        raise PaperStoreError("当前没有可用论文缓存，请先上传并解析 PDF。")

    try:
        payload = json.loads(CURRENT_PAPER_PATH.read_text(encoding="utf-8"))
        paper = PaperRecord.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise PaperStoreError("当前论文缓存已损坏，请重新上传 PDF。") from exc

    if expected_paper_id and paper.paper_id != expected_paper_id:
        raise PaperStoreError("paper_id 与当前缓存论文不一致，请重新上传或刷新页面后再试。")

    return paper


def save_current_analysis(analysis: PaperAnalysisResponse) -> None:
    """保存最近一次精读分析缓存。"""
    _ensure_data_dir()
    _write_json(
        CURRENT_ANALYSIS_PATH,
        {
            "cache_version": ANALYSIS_CACHE_VERSION,
            "analysis": analysis.model_dump(),
        },
    )


def load_current_analysis(expected_paper_id: str) -> PaperAnalysisResponse | None:
    """
    读取最近一次分析缓存；如果 schema 或缓存版本不兼容，则自动视为失效。
    这样旧的 current_analysis.json 不会在 B 轮继续命中。
    """
    if not CURRENT_ANALYSIS_PATH.exists():
        return None

    try:
        raw_payload = json.loads(CURRENT_ANALYSIS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        clear_current_analysis()
        return None

    if not isinstance(raw_payload, dict):
        clear_current_analysis()
        return None

    if raw_payload.get("cache_version") != ANALYSIS_CACHE_VERSION:
        clear_current_analysis()
        return None

    payload = raw_payload.get("analysis")
    if not isinstance(payload, dict):
        clear_current_analysis()
        return None

    try:
        analysis = PaperAnalysisResponse.model_validate(payload)
    except ValidationError:
        clear_current_analysis()
        return None

    if analysis.paper_id != expected_paper_id:
        return None

    return analysis


async def save_current_pdf(file: UploadFile, paper_id: str) -> None:
    """保存当前论文原始 PDF，供公式截图按需裁剪时复用。"""
    try:
        _ensure_data_dir()
        PAPER_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        for cached_pdf in PAPER_CACHE_DIR.glob("*.pdf"):
            cached_pdf.unlink()

        destination = PAPER_CACHE_DIR / f"{paper_id}.pdf"
        await file.seek(0)

        with destination.open("wb") as target:
            shutil.copyfileobj(file.file, target)
    except OSError as exc:
        raise PaperStoreError("当前论文原始 PDF 保存失败，请稍后重试。") from exc


def load_current_pdf_path(expected_paper_id: str) -> Path:
    """读取当前缓存 PDF 的路径，并校验它与当前 paper_id 一致。"""
    paper = load_current_paper(expected_paper_id)
    pdf_path = PAPER_CACHE_DIR / f"{paper.paper_id}.pdf"

    if not pdf_path.exists():
        raise PaperStoreError("当前论文原始 PDF 不存在，请重新上传并解析。")

    return pdf_path


def clear_current_analysis() -> None:
    """上传新论文后，旧分析缓存不再适用，直接删除。"""
    if CURRENT_ANALYSIS_PATH.exists():
        CURRENT_ANALYSIS_PATH.unlink()


def save_current_section_embeddings(cache: SectionEmbeddingsCache) -> None:
    """保存当前论文的 section embeddings 缓存。"""
    _ensure_data_dir()
    _write_json(CURRENT_SECTION_EMBEDDINGS_PATH, cache.model_dump())


def load_current_section_embeddings(expected_paper_id: str) -> SectionEmbeddingsCache | None:
    """
    读取 section embeddings 缓存。
    同时做 cache_version + paper_id 双校验，不兼容时自动视为失效。
    """
    if not CURRENT_SECTION_EMBEDDINGS_PATH.exists():
        return None

    try:
        payload = json.loads(CURRENT_SECTION_EMBEDDINGS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        clear_current_section_embeddings()
        return None

    if not isinstance(payload, dict):
        clear_current_section_embeddings()
        return None

    if payload.get("cache_version") != SECTION_EMBEDDINGS_CACHE_VERSION:
        clear_current_section_embeddings()
        return None

    if payload.get("paper_id") != expected_paper_id:
        clear_current_section_embeddings()
        return None

    try:
        return SectionEmbeddingsCache.model_validate(payload)
    except ValidationError:
        clear_current_section_embeddings()
        return None


def clear_current_section_embeddings() -> None:
    """上传新论文后，旧 section embeddings 缓存不再适用。"""
    if CURRENT_SECTION_EMBEDDINGS_PATH.exists():
        CURRENT_SECTION_EMBEDDINGS_PATH.unlink()


def clear_equation_cache() -> None:
    """上传新论文后，旧公式截图缓存也一起失效。"""
    if EQUATION_CACHE_DIR.exists():
        shutil.rmtree(EQUATION_CACHE_DIR)


def save_current_mineru_assets(
    *,
    paper_id: str,
    source_output_dir: Path,
    image_relative_paths: set[str],
) -> None:
    """
    缓存 MinerU 已经产出的原始公式图片。
    这里只复制 MinerU 输出资产，不做额外截图生成。
    """
    try:
        _ensure_data_dir()
        target_root = MINERU_ASSET_DIR / paper_id

        if target_root.exists():
            shutil.rmtree(target_root)

        for child in MINERU_ASSET_DIR.iterdir() if MINERU_ASSET_DIR.exists() else []:
            if child.is_dir() and child.name != paper_id:
                shutil.rmtree(child)

        for relative_path in image_relative_paths:
            if not relative_path:
                continue

            source_path = source_output_dir / relative_path
            if not source_path.exists():
                continue

            destination_path = target_root / relative_path
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination_path)
    except OSError as exc:
        raise PaperStoreError("MinerU 输出资产缓存失败，请重新上传论文后再试。") from exc


def resolve_current_mineru_asset_path(paper_id: str, relative_path: str) -> Path:
    asset_path = MINERU_ASSET_DIR / paper_id / relative_path
    if not asset_path.exists():
        raise PaperStoreError("当前公式原始图片不存在，请重新上传论文。")

    return asset_path


def load_parsed_paper_cache(pdf_sha256: str) -> PaperContent | None:
    """
    读取按 PDF SHA-256 命中的解析缓存。
    缓存损坏、版本不兼容或关键文件缺失时，自动降级为 cache miss。
    """
    cache_dir = _get_parse_cache_dir(pdf_sha256)
    meta_path = cache_dir / "meta.json"
    paper_content_path = cache_dir / "paper_content.json"
    source_pdf_path = cache_dir / "source.pdf"

    if not cache_dir.exists():
        return None

    if not meta_path.exists() or not paper_content_path.exists() or not source_pdf_path.exists():
        logger.warning(
            "Parsed paper cache INVALID_FALLBACK for %s: required files missing, removing cache dir.",
            pdf_sha256,
        )
        remove_parsed_paper_cache(pdf_sha256)
        return None

    try:
        meta_payload = json.loads(meta_path.read_text(encoding="utf-8"))
        content_payload = json.loads(paper_content_path.read_text(encoding="utf-8"))
        meta = ParsedPaperCacheMeta.model_validate(meta_payload)
        paper_content = PaperContent.model_validate(content_payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning(
            "Parsed paper cache INVALID_FALLBACK for %s: %s. Removing cache dir.",
            pdf_sha256,
            exc,
        )
        remove_parsed_paper_cache(pdf_sha256)
        return None

    if meta.cache_version != PARSED_PAPER_CACHE_VERSION:
        logger.info(
            "Parsed paper cache INVALID_FALLBACK for %s: cache version %s != %s, removing cache dir.",
            pdf_sha256,
            meta.cache_version,
            PARSED_PAPER_CACHE_VERSION,
        )
        remove_parsed_paper_cache(pdf_sha256)
        return None

    if meta.pdf_sha256 != pdf_sha256:
        logger.warning(
            "Parsed paper cache INVALID_FALLBACK for %s: meta sha256 mismatch, removing cache dir.",
            pdf_sha256,
        )
        remove_parsed_paper_cache(pdf_sha256)
        return None

    return paper_content


def save_parsed_paper_cache_from_current_session(
    pdf_sha256: str,
    paper_id: str,
    original_filename: str,
    paper_content: PaperContent,
) -> None:
    """
    把当前会话中已经成功解析的结果回写到 parse_cache。
    这里只缓存产品实际依赖的结构化结果、原始 PDF 和 MinerU 资产。
    """
    _ensure_data_dir()
    cache_dir = _get_parse_cache_dir(pdf_sha256)
    source_pdf_path = PAPER_CACHE_DIR / f"{paper_id}.pdf"
    current_assets_dir = MINERU_ASSET_DIR / paper_id

    if not source_pdf_path.exists():
        raise PaperStoreError("当前会话 PDF 不存在，无法写入解析缓存。")

    if cache_dir.exists():
        shutil.rmtree(cache_dir)

    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "mineru_assets").mkdir(parents=True, exist_ok=True)

    meta = ParsedPaperCacheMeta(
        cache_version=PARSED_PAPER_CACHE_VERSION,
        pdf_sha256=pdf_sha256,
        original_filename=original_filename,
        saved_at=datetime.now(timezone.utc).isoformat(),
    )
    _write_json(cache_dir / "meta.json", meta.model_dump())
    _write_json(cache_dir / "paper_content.json", paper_content.model_dump())
    shutil.copy2(source_pdf_path, cache_dir / "source.pdf")

    if current_assets_dir.exists():
        shutil.copytree(
            current_assets_dir,
            cache_dir / "mineru_assets",
            dirs_exist_ok=True,
        )


def restore_parsed_paper_cache_to_current_session(pdf_sha256: str, paper_id: str) -> None:
    """
    把 parse_cache 中的 PDF 和 MinerU 资产恢复成当前会话目录结构。
    如果缓存文件缺失，则抛错交给上传链路自动降级为 cache miss。
    """
    cache_dir = _get_parse_cache_dir(pdf_sha256)
    source_pdf_path = cache_dir / "source.pdf"
    cached_assets_dir = cache_dir / "mineru_assets"
    destination_pdf_path = PAPER_CACHE_DIR / f"{paper_id}.pdf"
    destination_assets_dir = MINERU_ASSET_DIR / paper_id

    if not source_pdf_path.exists():
        raise PaperStoreError("解析缓存中的 source.pdf 缺失，无法恢复当前会话。")

    _ensure_data_dir()
    PAPER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _clear_current_pdf_cache()
    shutil.copy2(source_pdf_path, destination_pdf_path)

    _clear_current_mineru_asset_cache(except_paper_id=paper_id)
    if destination_assets_dir.exists():
        shutil.rmtree(destination_assets_dir)

    if cached_assets_dir.exists():
        shutil.copytree(cached_assets_dir, destination_assets_dir)


def remove_parsed_paper_cache(pdf_sha256: str) -> None:
    """删除指定 PDF SHA-256 对应的解析缓存目录。"""
    cache_dir = _get_parse_cache_dir(pdf_sha256)
    if not cache_dir.exists():
        return

    shutil.rmtree(cache_dir)


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _get_parse_cache_dir(pdf_sha256: str) -> Path:
    return PARSE_CACHE_DIR / pdf_sha256


def _clear_current_pdf_cache() -> None:
    for cached_pdf in PAPER_CACHE_DIR.glob("*.pdf"):
        cached_pdf.unlink()


def _clear_current_mineru_asset_cache(*, except_paper_id: str | None = None) -> None:
    if not MINERU_ASSET_DIR.exists():
        return

    for child in MINERU_ASSET_DIR.iterdir():
        if not child.is_dir():
            continue

        if except_paper_id and child.name == except_paper_id:
            continue

        shutil.rmtree(child)
