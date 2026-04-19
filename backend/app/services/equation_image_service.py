from pathlib import Path

import fitz
from PIL import Image

from app.schemas.paper import PaperRecord, SectionBlock
from app.services.paper_store import (
    DATA_DIR,
    load_current_paper,
    load_current_pdf_path,
    resolve_current_mineru_asset_path,
)


EQUATION_IMAGE_SCALE = 2.5
EQUATION_IMAGE_PADDING = 6.0
EQUATION_IMAGE_DIR = DATA_DIR / "equations"
MINERU_RENDER_DPI = 120


class EquationImageError(RuntimeError):
    """公式截图按需生成失败时抛出的统一异常。"""


def get_or_create_equation_image(paper_id: str, equation_id: str) -> Path:
    """
    先尝试读取已有缓存；若不存在，再按 page_idx + bbox 从当前 PDF 裁剪公式区域。
    这样不会拖慢上传，只在前端确实需要 fallback 时生成图片。
    """
    paper = load_current_paper(paper_id)
    equation_block = _find_equation_block(paper, equation_id)

    if equation_block.page_idx is None or len(equation_block.bbox) != 4:
        raise EquationImageError("当前公式缺少 page_idx 或 bbox，无法生成截图。")

    image_path = EQUATION_IMAGE_DIR / paper_id / f"{equation_id}.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if equation_block.source_image_path:
            source_image_path = resolve_current_mineru_asset_path(
                paper_id,
                equation_block.source_image_path,
            )
            if image_path.exists() and image_path.stat().st_mtime >= source_image_path.stat().st_mtime:
                return image_path
            _save_source_image(source_image_path, image_path)
            return image_path

        if image_path.exists():
            return image_path

        pdf_path = load_current_pdf_path(paper_id)
        with fitz.open(pdf_path) as document:
            page = document.load_page(equation_block.page_idx)
            if _looks_like_pdf_space_bbox(page.rect, equation_block.bbox):
                clip_rect = _build_clip_rect(page.rect, equation_block.bbox)
                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(EQUATION_IMAGE_SCALE, EQUATION_IMAGE_SCALE),
                    clip=clip_rect,
                    alpha=False,
                )
                pixmap.save(image_path)
            else:
                _save_raster_crop(page, equation_block.bbox, image_path)
    except (RuntimeError, ValueError) as exc:
        raise EquationImageError("公式截图生成失败，请重新上传论文后再试。") from exc

    return image_path


def _find_equation_block(paper: PaperRecord, equation_id: str) -> SectionBlock:
    for section in paper.sections:
        for block in section.blocks:
            if block.block_type == "equation" and block.equation_id == equation_id:
                return block

    raise EquationImageError("未找到对应的公式块，请重新上传论文后再试。")


def _build_clip_rect(page_rect: fitz.Rect, bbox: list[float]) -> fitz.Rect:
    rect = fitz.Rect(*bbox)
    rect = fitz.Rect(
        rect.x0 - EQUATION_IMAGE_PADDING,
        rect.y0 - EQUATION_IMAGE_PADDING,
        rect.x1 + EQUATION_IMAGE_PADDING,
        rect.y1 + EQUATION_IMAGE_PADDING,
    )
    rect = rect & page_rect

    if rect.is_empty or rect.width <= 0 or rect.height <= 0:
        raise EquationImageError("当前公式 bbox 无效，无法生成截图。")

    return rect


def _looks_like_pdf_space_bbox(page_rect: fitz.Rect, bbox: list[float]) -> bool:
    return bbox[2] <= page_rect.width + 1 and bbox[3] <= page_rect.height + 1


def _save_raster_crop(page: fitz.Page, bbox: list[float], image_path: Path) -> None:
    page_pixmap = page.get_pixmap(dpi=MINERU_RENDER_DPI, alpha=False)
    image = Image.frombytes("RGB", [page_pixmap.width, page_pixmap.height], page_pixmap.samples)

    left = max(0, int(bbox[0] - EQUATION_IMAGE_PADDING))
    top = max(0, int(bbox[1] - EQUATION_IMAGE_PADDING))
    right = min(image.width, int(bbox[2] + EQUATION_IMAGE_PADDING))
    bottom = min(image.height, int(bbox[3] + EQUATION_IMAGE_PADDING))

    if right <= left or bottom <= top:
        raise EquationImageError("当前公式 bbox 无效，无法生成截图。")

    image.crop((left, top, right, bottom)).save(image_path)


def _save_source_image(source_image_path: Path, target_image_path: Path) -> None:
    with Image.open(source_image_path) as image:
        image.convert("RGB").save(target_image_path, format="PNG")
