import logging
import math
import re
from dataclasses import dataclass

from app.schemas.paper import PaperRecord, Section, SectionBlock
from app.services.ollama_client import OLLAMA_EMBED_MODEL, generate_embeddings
from app.services.paper_store import (
    SECTION_EMBEDDINGS_CACHE_VERSION,
    SectionEmbeddingItem,
    SectionEmbeddingsCache,
    load_current_section_embeddings,
    save_current_section_embeddings,
)


logger = logging.getLogger(__name__)

MAX_SECTION_EMBED_TEXT_CHARS = 1400
MAX_ROUTED_SECTIONS = 3
MAX_ROUTED_CONTEXT_CHARS = 3800
MAX_SECTION_ONLY_SECTION_CHARS = 1200
MAX_TEXT_SNIPPETS = 5
MAX_FORMULA_WINDOWS = 4
MAX_TEXT_BLOCK_CHARS = 520
MAX_SECTION_CONTENT_FALLBACK_CHARS = 720
SECTION_SCORE_WEIGHT = 4.0

QUESTION_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,}|[\u4e00-\u9fff]{2,6}")
EQUATION_NUMBER_PATTERN = re.compile(
    r"(?:eq(?:uation)?|formula|式|公式)\s*[\(\[（]?\s*(\d{1,3})\s*[\)\]）]?",
    re.IGNORECASE,
)
ANY_NUMBER_IN_BRACKETS_PATTERN = re.compile(r"[\(\[（]\s*(\d{1,3})\s*[\)\]）]")
EQUATION_TAG_PATTERN = re.compile(r"\\tag\{\s*(\d{1,3})\s*\}")

FORMULA_QUESTION_HINTS = {
    "公式",
    "推导",
    "约束",
    "控制律",
    "变量",
    "定理",
    "证明",
    "equation",
    "formula",
    "derivation",
    "constraint",
    "law",
    "theorem",
    "proof",
    "variable",
}


class SectionRoutingError(RuntimeError):
    """section 路由或 block 精排失败时抛出的异常。"""


@dataclass
class FocusedAskContext:
    context: str
    matched_headings: list[str]
    is_formula_question: bool


def try_prepare_section_embeddings(paper: PaperRecord) -> None:
    """
    upload 阶段的“尽力而为” embeddings 生成。
    失败时只记录日志，不影响上传主链路。
    """
    try:
        ensure_section_embeddings(paper)
    except Exception as exc:  # noqa: BLE001 - 上传阶段必须吞掉异常
        logger.warning("Section embeddings best-effort generation failed: %s", exc)


def ensure_section_embeddings(paper: PaperRecord) -> SectionEmbeddingsCache:
    """
    读取当前论文的 section embeddings。
    如果缓存不存在、schema 失效或模型变了，则重新生成。
    """
    cached = load_current_section_embeddings(paper.paper_id)
    if cached is not None and cached.model == OLLAMA_EMBED_MODEL:
        return cached

    section_texts = [_build_section_embedding_text(section) for section in paper.sections]
    embeddings = generate_embeddings(section_texts) if section_texts else []

    cache = SectionEmbeddingsCache(
        cache_version=SECTION_EMBEDDINGS_CACHE_VERSION,
        paper_id=paper.paper_id,
        model=OLLAMA_EMBED_MODEL,
        sections=[
            SectionEmbeddingItem(
                section_index=index,
                heading=paper.sections[index].heading,
                embedding=embedding,
            )
            for index, embedding in enumerate(embeddings)
        ],
    )
    save_current_section_embeddings(cache)
    return cache


def build_focused_ask_context(paper: PaperRecord, question: str) -> FocusedAskContext:
    """
    ask 阶段的核心路由逻辑：
    1. section 级 embeddings 粗路由
    2. block 级规则精排
    """
    top_sections, matched_headings, is_formula_question = _route_top_sections(paper, question)
    question_tokens = _extract_question_tokens(question)
    equation_numbers = _extract_equation_numbers(question)

    snippet_candidates: list[tuple[float, str]] = []
    for section_index, section_score in top_sections:
        section = paper.sections[section_index]

        if is_formula_question:
            snippet_candidates.extend(
                _select_equation_windows(
                    section=section,
                    section_score=section_score,
                    question_tokens=question_tokens,
                    equation_numbers=equation_numbers,
                )
            )
        else:
            snippet_candidates.extend(
                _select_text_snippets(
                    section=section,
                    section_score=section_score,
                    question_tokens=question_tokens,
                )
            )

    if not snippet_candidates:
        for section_index, section_score in top_sections:
            section = paper.sections[section_index]
            fallback_text = _build_section_fallback_text(section)
            if fallback_text:
                snippet_candidates.append(
                    (
                        section_score,
                        f"[Section] {section.heading}\n{fallback_text}",
                    )
                )

    snippet_candidates.sort(key=lambda item: item[0], reverse=True)
    context = _assemble_context(
        paper=paper,
        snippets=[text for _, text in snippet_candidates],
        matched_headings=matched_headings,
    )

    logger.info("Ask matched sections: %s", matched_headings)
    return FocusedAskContext(
        context=context,
        matched_headings=matched_headings,
        is_formula_question=is_formula_question,
    )


def build_section_only_ask_context(paper: PaperRecord, question: str) -> FocusedAskContext:
    """
    TEMP/ABLATION：只做 section embeddings top-k 路由，不做 block 精排和公式窗口。
    用于本地 ask 效果对比实验，后续可整体删除。
    """
    top_sections, matched_headings, is_formula_question = _route_top_sections(paper, question)
    context = _assemble_section_only_context(
        paper=paper,
        top_sections=top_sections,
        matched_headings=matched_headings,
    )

    logger.info("Ask matched sections (section_only): %s", matched_headings)
    return FocusedAskContext(
        context=context,
        matched_headings=matched_headings,
        is_formula_question=is_formula_question,
    )


def is_formula_question(question: str) -> bool:
    """给 TEMP/ABLATION global 模式复用当前公式问题识别逻辑。"""
    return _is_formula_question(question)


def _build_section_embedding_text(section: Section) -> str:
    content_text = _truncate_text(section.content or section.summary, MAX_SECTION_EMBED_TEXT_CHARS)
    return (
        f"标题：{section.heading}\n"
        f"摘要：{section.summary}\n"
        f"正文：{content_text}"
    )


def _route_top_sections(
    paper: PaperRecord,
    question: str,
) -> tuple[list[tuple[int, float]], list[str], bool]:
    if not paper.sections:
        raise SectionRoutingError("当前论文没有可用章节内容，无法做问答路由。")

    embeddings_cache = ensure_section_embeddings(paper)
    question_embedding_list = generate_embeddings([question])
    if not question_embedding_list:
        raise SectionRoutingError("问题向量生成失败，无法执行 section 路由。")

    question_embedding = question_embedding_list[0]
    ranked_sections = _rank_sections(paper, embeddings_cache, question_embedding, question)
    if not ranked_sections:
        raise SectionRoutingError("当前论文没有可用于路由的 section embeddings。")

    top_sections = ranked_sections[:MAX_ROUTED_SECTIONS]
    matched_headings = [paper.sections[index].heading for index, _ in top_sections]
    return top_sections, matched_headings, _is_formula_question(question)


def _rank_sections(
    paper: PaperRecord,
    embeddings_cache: SectionEmbeddingsCache,
    question_embedding: list[float],
    question: str | None = None,
) -> list[tuple[int, float]]:
    ranked: list[tuple[int, float]] = []
    question_tokens = _extract_question_tokens(question or "")
    equation_numbers = _extract_equation_numbers(question or "")
    is_formula_question = _is_formula_question(question or "")

    for item in embeddings_cache.sections:
        if item.section_index >= len(paper.sections):
            continue

        similarity = _cosine_similarity(question_embedding, item.embedding)
        section = paper.sections[item.section_index]
        similarity += 0.05 * _keyword_overlap_score(
            f"{section.heading} {section.summary}",
            question_tokens,
        )

        if is_formula_question and any(block.block_type == "equation" for block in section.blocks):
            similarity += 0.08

        if equation_numbers and _section_has_equation_tag(section, equation_numbers):
            similarity += 2.0

        ranked.append((item.section_index, similarity))

    ranked.sort(key=lambda entry: entry[1], reverse=True)
    return ranked


def _select_text_snippets(
    *,
    section: Section,
    section_score: float,
    question_tokens: set[str],
) -> list[tuple[float, str]]:
    candidates: list[tuple[float, str]] = []

    for block in section.blocks:
        if block.block_type != "text":
            continue

        block_score = _keyword_overlap_score(block.text, question_tokens)
        if block_score <= 0 and candidates:
            continue

        candidates.append(
            (
                block_score + section_score * SECTION_SCORE_WEIGHT,
                f"[Section] {section.heading}\n[Relevant text]\n{_truncate_text(block.text, MAX_TEXT_BLOCK_CHARS)}",
            )
        )

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[:MAX_TEXT_SNIPPETS]


def _select_equation_windows(
    *,
    section: Section,
    section_score: float,
    question_tokens: set[str],
    equation_numbers: set[str],
) -> list[tuple[float, str]]:
    candidates: list[tuple[float, str]] = []

    for index, block in enumerate(section.blocks):
        if block.block_type != "equation":
            continue

        prev_text_block = _find_neighbor_text_block(section.blocks, index, direction=-1)
        next_text_block = _find_neighbor_text_block(section.blocks, index, direction=1)
        equation_tag = _extract_equation_tag(block.text)

        local_text = " ".join(
            part
            for part in [
                prev_text_block.text if prev_text_block else "",
                block.text,
                next_text_block.text if next_text_block else "",
            ]
            if part
        )

        score = section_score * SECTION_SCORE_WEIGHT + 3.0
        score += _keyword_overlap_score(local_text, question_tokens)
        if equation_numbers and equation_tag and equation_tag in equation_numbers:
            score += 6.0

        parts = [f"[Section] {section.heading}", "[Equation context]"]
        if prev_text_block:
            parts.append(f"前文：{_truncate_text(prev_text_block.text, MAX_TEXT_BLOCK_CHARS)}")
        parts.append(f"公式：{block.text}")
        if next_text_block:
            parts.append(f"后文：{_truncate_text(next_text_block.text, MAX_TEXT_BLOCK_CHARS)}")

        candidates.append((score, "\n".join(parts)))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[:MAX_FORMULA_WINDOWS]


def _assemble_context(
    *,
    paper: PaperRecord,
    snippets: list[str],
    matched_headings: list[str],
) -> str:
    lines = [
        f"论文标题：{paper.title}",
        f"论文摘要：{paper.abstract}",
        "",
        "已匹配章节：",
        *[f"- {heading}" for heading in matched_headings],
        "",
        "聚焦上下文：",
    ]
    used_chars = sum(len(line) for line in lines)

    for snippet in snippets:
        remaining_chars = MAX_ROUTED_CONTEXT_CHARS - used_chars
        if remaining_chars <= 120:
            break

        snippet_text = _truncate_text(snippet, remaining_chars)
        lines.append(snippet_text)
        lines.append("")
        used_chars += len(snippet_text)

    return "\n".join(lines).strip()


def _assemble_section_only_context(
    *,
    paper: PaperRecord,
    top_sections: list[tuple[int, float]],
    matched_headings: list[str],
) -> str:
    lines = [
        f"论文标题：{paper.title}",
        f"论文摘要：{paper.abstract}",
        "",
        "已匹配章节：",
        *[f"- {heading}" for heading in matched_headings],
        "",
        "聚焦上下文：",
    ]
    used_chars = sum(len(line) for line in lines)

    for section_index, _ in top_sections:
        remaining_chars = MAX_ROUTED_CONTEXT_CHARS - used_chars
        if remaining_chars <= 120:
            break

        section = paper.sections[section_index]
        section_text = _build_section_only_text(section, remaining_chars)
        if not section_text:
            continue

        lines.append(section_text)
        lines.append("")
        used_chars += len(section_text)

    return "\n".join(lines).strip()


def _build_section_only_text(section: Section, max_chars: int) -> str:
    section_body = (section.content or "").strip() or section.summary.strip()
    if not section_body:
        return ""

    body_max_chars = min(MAX_SECTION_ONLY_SECTION_CHARS, max_chars)
    return (
        f"[Section] {section.heading}\n"
        f"{_truncate_text(section_body, body_max_chars)}"
    )


def _build_section_fallback_text(section: Section) -> str:
    content = section.content.strip()
    if content:
        return _truncate_text(content, MAX_SECTION_CONTENT_FALLBACK_CHARS)

    summary = section.summary.strip()
    if summary:
        return _truncate_text(summary, MAX_SECTION_CONTENT_FALLBACK_CHARS)

    return ""


def _find_neighbor_text_block(
    blocks: list[SectionBlock],
    start_index: int,
    *,
    direction: int,
) -> SectionBlock | None:
    index = start_index + direction
    while 0 <= index < len(blocks):
        block = blocks[index]
        if block.block_type == "text" and block.text.strip():
            return block
        index += direction

    return None


def _is_formula_question(question: str) -> bool:
    lowered = question.lower()
    if any(hint in lowered for hint in FORMULA_QUESTION_HINTS):
        return True

    if "$" in question or "\\" in question:
        return True

    if EQUATION_NUMBER_PATTERN.search(question):
        return True

    return False


def _extract_question_tokens(question: str) -> set[str]:
    lowered = question.lower()
    tokens = {
        token.lower()
        for token in QUESTION_TOKEN_PATTERN.findall(question)
        if len(token.strip()) >= 2
    }
    for hint in FORMULA_QUESTION_HINTS:
        if hint in lowered:
            tokens.add(hint)
    return tokens


def _extract_equation_numbers(question: str) -> set[str]:
    numbers = {match for match in EQUATION_NUMBER_PATTERN.findall(question) if match}
    if numbers:
        return numbers

    if _is_formula_question(question):
        return {match for match in ANY_NUMBER_IN_BRACKETS_PATTERN.findall(question) if match}

    return set()


def _extract_equation_tag(text: str) -> str:
    match = EQUATION_TAG_PATTERN.search(text)
    if match:
        return match.group(1)

    return ""


def _section_has_equation_tag(section: Section, equation_numbers: set[str]) -> bool:
    if not equation_numbers:
        return False

    for block in section.blocks:
        if block.block_type != "equation":
            continue

        equation_tag = _extract_equation_tag(block.text)
        if equation_tag and equation_tag in equation_numbers:
            return True

    return False


def _keyword_overlap_score(text: str, question_tokens: set[str]) -> float:
    lowered = text.lower()
    score = 0.0
    for token in question_tokens:
        if token in lowered:
            score += 1.0
    return score


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0

    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))

    if left_norm == 0 or right_norm == 0:
        return 0.0

    return numerator / (left_norm * right_norm)


def _truncate_text(text: str, max_chars: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned

    return f"{cleaned[:max_chars].rstrip()}..."
