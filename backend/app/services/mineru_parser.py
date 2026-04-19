import json
import locale
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi import UploadFile

from app.schemas.paper import PaperContent, Section, SectionBlock
from app.services.paper_store import save_current_mineru_assets


MINERU_MODULE = "mineru.cli.client"
MINERU_BACKEND = "pipeline"
MINERU_IMPORT_CHECK_TIMEOUT_SECONDS = 20
MINERU_RUNTIME_DIR = Path(__file__).resolve().parents[2] / "runtime_bootstrap"
MINERU_FASTLANG_MODEL_PATH = MINERU_RUNTIME_DIR / "resources" / "lid.176.ftz"
MINERU_FASTLANG_CACHE_DIR = MINERU_RUNTIME_DIR / "fasttext-langdetect"
ABSTRACT_MAX_CHARS = 1600
SECTION_SUMMARY_MAX_CHARS = 280
SECTION_CONTENT_MAX_CHARS = 1800
MAX_SECTIONS = 12
MIN_SECTION_BLOCK_CHARS = 80

EXCLUDED_TITLE_TEXTS = {
    "abstract",
    "摘要",
    "introduction",
    "1 introduction",
    "contents",
    "目录",
}

SKIPPED_SECTION_HEADINGS = {
    "abstract",
    "摘要",
    "keywords",
    "keyword",
    "关键词",
}

SECTION_HEADING_PATTERN = re.compile(
    r"^(\d+(\.\d+)*|[IVXLC]+)\s*[\.\-:]?\s+[A-Za-z][A-Za-z0-9 \-/]{1,120}$"
)

COMMON_SECTION_HEADINGS = {
    "abstract",
    "摘要",
    "introduction",
    "related work",
    "background",
    "method",
    "methods",
    "approach",
    "experiment",
    "experiments",
    "results",
    "discussion",
    "conclusion",
    "references",
}

IGNORED_CONTENT_ITEM_TYPES = {
    "header",
    "footer",
    "page_number",
    "page_footnote",
    "image",
    "chart",
    "table",
}

DOCUMENT_NOISE_PATTERNS = [
    re.compile(
        r"[A-Z][A-Z .,:–-]+TARGET ENCLOSING CONTROL FOR UNMANNED AERIAL VEHICLE SWARM\s+\d+",
        re.IGNORECASE,
    ),
    re.compile(r"Authorized licensed use limited to:.*?Restrictions apply\.", re.IGNORECASE),
    re.compile(r"Downloaded on .*? UTC from IEEE Xplore\.", re.IGNORECASE),
    re.compile(r"IEEE/ASME TRANSACTIONS ON .*?(?= [A-Z][a-z]|$)", re.IGNORECASE),
]

SUSPICIOUS_LATEX_PATTERNS = [
    re.compile(r"\\begin\b(?!.*\\end\b)", re.DOTALL),
    re.compile(r"\\end\b(?!.*\\begin\b)", re.DOTALL),
    re.compile(r"\\left(?!.*\\right)", re.DOTALL),
    re.compile(r"\\right(?!.*\\left)", re.DOTALL),
    re.compile(r"[_^]\s*$"),
]


class MineruParseError(RuntimeError):
    """MinerU 解析失败时抛出的统一异常。"""


async def parse_pdf_with_mineru(file: UploadFile, paper_id: str = "") -> PaperContent:
    """保存上传文件、调用 MinerU，并把结果整理成前端需要的结构。"""
    original_name = Path(file.filename or "upload.pdf").name

    with TemporaryDirectory(prefix="paper_reader_") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        pdf_path = temp_dir / original_name
        output_dir = temp_dir / "mineru_output"

        await _save_upload_file(file, pdf_path)
        _run_mineru_cli(pdf_path, output_dir)

        content_list_path = _find_content_list_file(output_dir)
        content_items = _load_content_items(content_list_path)
        if paper_id:
            save_current_mineru_assets(
                paper_id=paper_id,
                source_output_dir=content_list_path.parent,
                image_relative_paths=_collect_equation_image_paths(content_items),
            )

    return _build_paper_response(content_items, fallback_title=original_name)


async def _save_upload_file(file: UploadFile, destination: Path) -> None:
    """先把上传的 PDF 落到临时目录，方便交给 MinerU 处理。"""
    await file.seek(0)

    with destination.open("wb") as target:
        shutil.copyfileobj(file.file, target)


def _run_mineru_cli(pdf_path: Path, output_dir: Path) -> None:
    """调用当前 Python 环境中的 MinerU，避免误用系统 PATH 中的其他版本。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    mineru_python = _resolve_mineru_python()
    command_env = _build_mineru_command_env(mineru_python)
    command = [
        str(mineru_python),
        "-m",
        MINERU_MODULE,
        "-p",
        str(pdf_path),
        "-o",
        str(output_dir),
        "-b",
        MINERU_BACKEND,
    ]

    try:
        result = subprocess.run(command, capture_output=True, check=False, env=command_env)
    except FileNotFoundError as exc:
        raise MineruParseError(
            "当前 Python 环境中未找到 MinerU。请先安装 backend/requirements.txt 中的依赖。"
        ) from exc

    if result.returncode != 0:
        stderr_text = _decode_subprocess_output(result.stderr)
        stdout_text = _decode_subprocess_output(result.stdout)
        error_message = stderr_text.strip() or stdout_text.strip() or "MinerU 命令执行失败。"
        raise MineruParseError(f"MinerU 解析失败：{error_message}")


def _resolve_mineru_python() -> Path:
    """
    优先使用项目 .venv 的 Python。
    这样即使后端是用系统 Python 启动的，也能稳定调用已安装完整依赖的 MinerU 环境。
    """
    candidate_strings: list[str] = []
    env_python = os.getenv("MINERU_PYTHON", "").strip()
    if env_python:
        candidate_strings.append(env_python)

    project_root = Path(__file__).resolve().parents[3]
    candidate_strings.extend(
        [
            str(project_root / ".venv" / "Scripts" / "python.exe"),
            str(project_root / ".venv" / "bin" / "python"),
            str(Path(sys.executable)),
        ]
    )

    for executable_name in ("python", "python3"):
        resolved = shutil.which(executable_name)
        if resolved:
            candidate_strings.append(resolved)

    candidate_strings.extend(_collect_py_launcher_candidates())

    candidates = [
        Path(candidate)
        for candidate in dict.fromkeys(candidate_strings)
        if candidate
    ]

    for candidate in candidates:
        if candidate.exists() and _python_has_mineru(candidate):
            return candidate

    if env_python:
        raise MineruParseError(
            f"MINERU_PYTHON 指向的解释器不可用或未安装 mineru：{env_python}"
        )

    raise MineruParseError(
        "未找到可用的 MinerU Python 解释器。"
        "请安装 backend/requirements.txt，或设置 MINERU_PYTHON 指向可 `import mineru` 的 Python。"
    )


def _python_has_mineru(python_path: Path) -> bool:
    try:
        result = subprocess.run(
            [str(python_path), "-c", "import mineru"],
            capture_output=True,
            check=False,
            timeout=MINERU_IMPORT_CHECK_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return False

    return result.returncode == 0


def _collect_py_launcher_candidates() -> list[str]:
    """
    Windows 下额外利用 `py -0p` 枚举已安装解释器。
    这样即使当前后端跑在没有 mineru 的 IDE 虚拟环境里，仍有机会找到系统 Python。
    """
    try:
        result = subprocess.run(
            ["py", "-0p"],
            capture_output=True,
            check=False,
            timeout=MINERU_IMPORT_CHECK_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return []

    if result.returncode != 0:
        return []

    stdout_text = _decode_subprocess_output(result.stdout)
    if not stdout_text:
        return []

    candidates: list[str] = []
    for raw_line in stdout_text.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue

        path_match = re.search(r"([A-Za-z]:\\.+)$", line)
        if not path_match:
            continue

        path = path_match.group(1).strip()
        if path:
            candidates.append(path)

    return candidates


def _decode_subprocess_output(raw_output: bytes | str | None) -> str:
    if raw_output is None:
        return ""

    if isinstance(raw_output, str):
        return raw_output

    encodings = [
        "utf-8",
        locale.getpreferredencoding(False) or "",
        "gbk",
    ]
    for encoding in dict.fromkeys(encoding for encoding in encodings if encoding):
        try:
            return raw_output.decode(encoding)
        except UnicodeDecodeError:
            continue

    return raw_output.decode("utf-8", errors="replace")


def _build_mineru_command_env(mineru_python: Path) -> dict[str, str]:
    env = os.environ.copy()
    bootstrap_dir = MINERU_RUNTIME_DIR
    bootstrap_dir.mkdir(parents=True, exist_ok=True)

    existing_pythonpath = env.get("PYTHONPATH", "").strip()
    pythonpath_parts = [str(bootstrap_dir)]
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)

    fastlang_model_path = _prepare_fastlang_small_model_copy(mineru_python)
    env["FAST_LANGDETECT_SMALL_MODEL_PATH"] = str(fastlang_model_path)
    env["FTLANG_CACHE"] = str(MINERU_FASTLANG_CACHE_DIR)

    return env


def _prepare_fastlang_small_model_copy(mineru_python: Path) -> Path:
    source_path = _resolve_fastlang_small_model_source(mineru_python)
    if not source_path.exists():
        raise MineruParseError(
            f"fast_langdetect 小模型不存在：{source_path}"
        )

    MINERU_FASTLANG_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    if (
        not MINERU_FASTLANG_MODEL_PATH.exists()
        or MINERU_FASTLANG_MODEL_PATH.stat().st_size != source_path.stat().st_size
    ):
        shutil.copy2(source_path, MINERU_FASTLANG_MODEL_PATH)

    return MINERU_FASTLANG_MODEL_PATH


def _resolve_fastlang_small_model_source(mineru_python: Path) -> Path:
    try:
        result = subprocess.run(
            [
                str(mineru_python),
                "-c",
                (
                    "from pathlib import Path; "
                    "import fast_langdetect.ft_detect.infer as infer; "
                    "print(Path(infer.LOCAL_SMALL_MODEL_PATH))"
                ),
            ],
            capture_output=True,
            check=False,
            timeout=MINERU_IMPORT_CHECK_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
        raise MineruParseError("无法定位 fast_langdetect 小模型路径。") from exc

    stdout_text = _decode_subprocess_output(result.stdout).strip()
    stderr_text = _decode_subprocess_output(result.stderr).strip()
    if result.returncode != 0 or not stdout_text:
        detail = stderr_text or stdout_text or "未知错误"
        raise MineruParseError(f"无法定位 fast_langdetect 小模型路径：{detail}")

    return Path(stdout_text)


def _find_content_list_file(output_dir: Path) -> Path:
    """MinerU 会输出 content_list.json，这里递归查找以兼容目录差异。"""
    matches = sorted(output_dir.rglob("*_content_list.json"))
    if not matches:
        matches = sorted(output_dir.rglob("content_list.json"))

    if not matches:
        raise MineruParseError("MinerU 解析完成，但没有找到 content_list.json 输出文件。")

    return matches[0]


def _load_content_items(content_list_path: Path) -> list[dict[str, Any]]:
    """读取 MinerU 的扁平内容列表，后续从这里提取标题、摘要和 sections。"""
    try:
        content = json.loads(content_list_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MineruParseError("MinerU 输出的 content_list.json 不是有效的 JSON。") from exc

    if not isinstance(content, list):
        raise MineruParseError("MinerU 输出的 content_list.json 格式不符合预期。")

    return [item for item in content if isinstance(item, dict)]


def _build_paper_response(
    content_items: list[dict[str, Any]],
    fallback_title: str,
) -> PaperContent:
    """把 MinerU 的原始输出清洗成统一的 PaperContent。"""
    readable_items = [item for item in content_items if _is_relevant_content_item(item)]

    if not readable_items:
        raise MineruParseError("MinerU 已返回结果，但没有提取到可读文本内容。")

    title = _extract_title(readable_items) or f"未识别标题：{fallback_title}"
    abstract = _extract_abstract(readable_items, title)
    sections = _extract_sections(readable_items, title)

    if not abstract:
        abstract = _build_fallback_abstract(readable_items, title)

    if not sections:
        sections = _build_fallback_sections(readable_items, title)

    return PaperContent(
        title=title,
        abstract=abstract or "未能从 MinerU 输出中提取到摘要。",
        sections=sections,
    )


def _extract_title(readable_items: list[dict[str, Any]]) -> str:
    """优先从第一页中提取最像标题的文本块。"""
    for item in readable_items[:20]:
        if item.get("type") == "title" and _page_index(item) == 0:
            return _extract_text_from_item(item)

    for item in readable_items[:20]:
        text = _extract_text_from_item(item)
        if not text or _page_index(item) != 0:
            continue
        if _is_heading_item(item) and _normalize_text(text) not in EXCLUDED_TITLE_TEXTS:
            return text

    for item in readable_items[:20]:
        text = _extract_text_from_item(item)
        if text and _page_index(item) == 0 and _normalize_text(text) not in EXCLUDED_TITLE_TEXTS:
            return text

    return ""


def _extract_abstract(readable_items: list[dict[str, Any]], title: str) -> str:
    """优先识别 Abstract/摘要 标题，再抽取后面的正文片段。"""
    title_key = _normalize_text(title)
    abstract_start_index = None

    for index, item in enumerate(readable_items[:80]):
        text = _extract_text_from_item(item)
        if _normalize_text(text) in {"abstract", "摘要"}:
            abstract_start_index = index + 1
            break

    if abstract_start_index is not None:
        chunks: list[str] = []

        for item in readable_items[abstract_start_index:]:
            text = _extract_text_from_item(item)
            if not text:
                continue

            if _is_heading_item(item):
                normalized_text = _normalize_text(text)
                if normalized_text in {"keywords", "keyword", "关键词"}:
                    break
                break

            chunks.append(text)

            if len(" ".join(chunks)) >= ABSTRACT_MAX_CHARS:
                break

        return _truncate_text(" ".join(chunks), ABSTRACT_MAX_CHARS)

    chunks = []
    for item in readable_items[:40]:
        text = _extract_text_from_item(item)
        if not text:
            continue

        normalized_text = _normalize_text(text)
        if normalized_text == title_key or normalized_text in SKIPPED_SECTION_HEADINGS:
            continue

        if _is_heading_item(item):
            if chunks:
                break
            continue

        chunks.append(text)

        if len(" ".join(chunks)) >= ABSTRACT_MAX_CHARS:
            break

    return _truncate_text(" ".join(chunks), ABSTRACT_MAX_CHARS)


def _extract_sections(readable_items: list[dict[str, Any]], title: str) -> list[Section]:
    """根据 heading 文本块切分章节，保留正文块与公式块的边界。"""
    title_key = _normalize_text(title)
    sections: list[Section] = []
    current_heading = ""
    current_content_blocks: list[SectionBlock] = []
    current_summary_blocks: list[str] = []
    skip_until_next_heading = False
    equation_counter = 0

    for item in readable_items:
        text = _extract_text_from_item(item)
        if not text:
            continue

        normalized_text = _normalize_text(text)

        if normalized_text == title_key:
            continue

        if _is_heading_item(item):
            if current_heading:
                sections.append(
                    _build_section(
                        current_heading,
                        current_content_blocks,
                        current_summary_blocks,
                    )
                )

            current_content_blocks = []
            current_summary_blocks = []

            if normalized_text in SKIPPED_SECTION_HEADINGS:
                current_heading = ""
                skip_until_next_heading = normalized_text in {"abstract", "摘要"}
                continue

            current_heading = text
            skip_until_next_heading = False
            continue

        if skip_until_next_heading:
            continue

        if current_heading:
            equation_id = ""
            if _is_equation_item(item):
                equation_counter += 1
                equation_id = f"eq-{equation_counter:04d}"

            block = _extract_section_block(item, equation_id)
            if not block:
                continue

            current_content_blocks.append(block)
            if block.block_type != "equation":
                current_summary_blocks.append(block.text)

    if current_heading:
        sections.append(
            _build_section(
                current_heading,
                current_content_blocks,
                current_summary_blocks,
            )
        )

    cleaned_sections = [section for section in sections if section.summary]
    return cleaned_sections[:MAX_SECTIONS]


def _build_fallback_abstract(readable_items: list[dict[str, Any]], title: str) -> str:
    """如果没识别到摘要，就从开头正文截一段作为保底摘要。"""
    title_key = _normalize_text(title)
    chunks: list[str] = []

    for item in readable_items:
        text = _extract_text_from_item(item)
        if not text:
            continue

        normalized_text = _normalize_text(text)
        if normalized_text == title_key or _is_heading_item(item):
            continue

        chunks.append(text)

        if len(" ".join(chunks)) >= ABSTRACT_MAX_CHARS:
            break

    return _truncate_text(" ".join(chunks), ABSTRACT_MAX_CHARS)


def _build_fallback_sections(readable_items: list[dict[str, Any]], title: str) -> list[Section]:
    """如果没有识别到章节标题，就返回一个保底正文 section。"""
    title_key = _normalize_text(title)
    content_blocks: list[SectionBlock] = []
    summary_blocks: list[str] = []
    equation_counter = 0

    for item in readable_items:
        text = _extract_text_from_item(item)
        if not text:
            continue

        normalized_text = _normalize_text(text)
        if normalized_text == title_key or normalized_text in SKIPPED_SECTION_HEADINGS:
            continue

        if _is_heading_item(item):
            continue

        equation_id = ""
        if _is_equation_item(item):
            equation_counter += 1
            equation_id = f"eq-{equation_counter:04d}"

        block = _extract_section_block(item, equation_id)
        if not block:
            continue

        content_blocks.append(block)
        if block.block_type != "equation":
            summary_blocks.append(block.text)

    trimmed_blocks = _truncate_section_blocks(content_blocks, SECTION_CONTENT_MAX_CHARS)
    full_text = _join_content_blocks(trimmed_blocks)
    summary_text = _join_text_blocks(summary_blocks) or full_text
    summary = _truncate_preview_text(summary_text, SECTION_SUMMARY_MAX_CHARS)
    content = full_text
    if not summary:
        return []

    return [Section(heading="正文内容", summary=summary, content=content, blocks=trimmed_blocks)]


def _build_section(
    heading: str,
    content_blocks: list[SectionBlock],
    summary_blocks: list[str],
) -> Section:
    """章节 summary 用前几段正文，content 保留正文块与公式块。"""
    trimmed_blocks = _truncate_section_blocks(content_blocks, SECTION_CONTENT_MAX_CHARS)
    content_text = _join_content_blocks(trimmed_blocks)
    summary_source = _join_text_blocks(summary_blocks) or content_text
    summary = _truncate_preview_text(summary_source, SECTION_SUMMARY_MAX_CHARS)
    content = content_text

    if not summary:
        summary = "该章节在 MinerU 输出中未提取到足够正文。"

    if not content:
        content = summary

    return Section(heading=heading, summary=summary, content=content, blocks=trimmed_blocks)


def _is_heading_item(item: dict[str, Any]) -> bool:
    """MinerU 的 text_level >= 1 通常表示标题层级。"""
    if item.get("type") == "title":
        return True

    if _get_text_level(item) >= 1:
        return True

    return _looks_like_heading_text(_extract_text_from_item(item))


def _get_text_level(item: dict[str, Any]) -> int:
    text_level = item.get("text_level", 0)

    if isinstance(text_level, int):
        return text_level

    if isinstance(text_level, str) and text_level.isdigit():
        return int(text_level)

    return 0


def _page_index(item: dict[str, Any]) -> int:
    page_idx = item.get("page_idx", 0)

    if isinstance(page_idx, int):
        return page_idx

    if isinstance(page_idx, str) and page_idx.isdigit():
        return int(page_idx)

    return 0


def _extract_text_from_item(item: dict[str, Any]) -> str:
    """兼容不同类型内容块，尽量统一提取出可读文本。"""
    for key in ("text", "content", "code_body"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return _clean_text(value)

    list_items = item.get("list_items")
    if isinstance(list_items, list):
        merged = " ".join(part for part in list_items if isinstance(part, str))
        if merged.strip():
            return _clean_text(merged)

    return ""


def _clean_text(text: str) -> str:
    cleaned = " ".join(text.split())
    return _remove_document_noise(cleaned)


def _is_relevant_content_item(item: dict[str, Any]) -> bool:
    if item.get("type") in IGNORED_CONTENT_ITEM_TYPES:
        return False

    return bool(_extract_text_from_item(item))


def _normalize_text(text: str) -> str:
    return _clean_text(text).strip().lower()


def _looks_like_heading_text(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False

    if normalized in COMMON_SECTION_HEADINGS:
        return True

    if len(text) > 120:
        return False

    return bool(SECTION_HEADING_PATTERN.match(text.strip()))


def _truncate_text(text: str, max_chars: int) -> str:
    cleaned = _clean_text(text)
    if len(cleaned) <= max_chars:
        return cleaned

    return f"{cleaned[:max_chars].rstrip()}..."


def _truncate_block_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text

    return f"{text[:max_chars].rstrip()}..."


def _truncate_preview_text(text: str, max_chars: int) -> str:
    """
    给 section summary 做更保守的截断。
    如果截断点落在公式内部，就回退到公式开始之前，避免前端看到半个 $...$ / $$...$$。
    """
    cleaned = _clean_text(text)
    if len(cleaned) <= max_chars:
        return cleaned

    state = "text"
    current_formula_start = -1
    safe_cutoff = 0
    index = 0

    while index < len(cleaned) and index < max_chars:
        if cleaned.startswith("$$", index):
            if state == "display_math":
                state = "text"
                current_formula_start = -1
                index += 2
                safe_cutoff = index
                continue

            if state == "text":
                state = "display_math"
                current_formula_start = index
                index += 2
                continue

        if cleaned[index] == "$":
            if state == "inline_math":
                state = "text"
                current_formula_start = -1
                index += 1
                safe_cutoff = index
                continue

            if state == "text":
                state = "inline_math"
                current_formula_start = index
                index += 1
                continue

        index += 1
        if state == "text":
            safe_cutoff = index

    if state == "text" and safe_cutoff > 0:
        cutoff = safe_cutoff
    elif current_formula_start > 40:
        cutoff = current_formula_start
    elif safe_cutoff > 0:
        cutoff = safe_cutoff
    else:
        cutoff = max_chars

    preview = cleaned[:cutoff].rstrip()
    if not preview:
        preview = cleaned[:max_chars].rstrip()

    return f"{preview}..."


def _post_process_section_text(text: str) -> str:
    cleaned = _clean_text(text)
    cleaned = re.sub(r"\bp\s+p(?=[A-Z])", " ", cleaned)
    cleaned = re.sub(r"\bvFor\b", "For", cleaned)
    cleaned = re.sub(r"\bpThe\b", "The", cleaned)
    cleaned = _clean_math_expressions(cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def _clean_prose_block(text: str) -> str:
    return _post_process_section_text(text)


def _clean_equation_block(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return ""

    if not cleaned.startswith("$$"):
        cleaned = f"$$ {cleaned} $$"

    cleaned = _clean_math_expressions(cleaned)
    return re.sub(r"\$\$\s*", "$$", re.sub(r"\s*\$\$", "$$", cleaned))


def _extract_section_block(item: dict[str, Any], equation_id: str = "") -> SectionBlock | None:
    raw_text = item.get("text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        return None

    if _is_equation_item(item):
        cleaned_text = _clean_equation_block(raw_text)
        if not cleaned_text:
            return None

        return SectionBlock(
            block_type="equation",
            text=cleaned_text,
            equation_id=equation_id,
            source_image_path=_extract_source_image_path(item),
            page_idx=_page_index(item),
            bbox=_extract_bbox(item),
            is_suspicious=_is_suspicious_equation(cleaned_text),
        )

    cleaned_text = _clean_prose_block(raw_text)
    if not cleaned_text:
        return None

    return SectionBlock(block_type="text", text=cleaned_text)


def _join_content_blocks(blocks: list[SectionBlock]) -> str:
    normalized_blocks = [block.text.strip() for block in blocks if block.text and block.text.strip()]
    return "\n\n".join(normalized_blocks)


def _join_text_blocks(blocks: list[str]) -> str:
    normalized_blocks = [block.strip() for block in blocks if block and block.strip()]
    return "\n\n".join(normalized_blocks)


def _truncate_section_blocks(blocks: list[SectionBlock], max_chars: int) -> list[SectionBlock]:
    used_chars = 0
    result: list[SectionBlock] = []

    for block in blocks:
        block_text = block.text.strip()
        if not block_text:
            continue

        separator_chars = 2 if result else 0
        remaining_chars = max_chars - used_chars - separator_chars
        if remaining_chars <= MIN_SECTION_BLOCK_CHARS:
            break

        if len(block_text) <= remaining_chars:
            result.append(block)
            used_chars += separator_chars + len(block_text)
            continue

        if block.block_type == "equation":
            break

        result.append(block.model_copy(update={"text": _truncate_block_text(block_text, remaining_chars)}))
        break

    return result


def _remove_document_noise(text: str) -> str:
    cleaned = text

    for pattern in DOCUMENT_NOISE_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)

    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _clean_math_expressions(text: str) -> str:
    cleaned = re.sub(
        r"\$\$([\s\S]+?)\$\$",
        lambda match: f"$$_clean_placeholder_$$".replace(
            "_clean_placeholder_",
            _clean_formula_body(match.group(1)),
        ),
        text,
    )
    cleaned = re.sub(
        r"\$([^$\n]+?)\$",
        lambda match: f"${_clean_formula_body(match.group(1))}$",
        cleaned,
    )
    return cleaned


def _clean_formula_body(formula: str) -> str:
    cleaned = formula.strip()

    cleaned = re.sub(
        r"\\operatorname\*\s*\{\s*(([A-Za-z]\s*)+)\}",
        lambda match: r"\operatorname*{" + _compact_letters(match.group(1)) + "}",
        cleaned,
    )
    cleaned = re.sub(
        r"\\mathrm\s*\{\s*(([A-Za-z]\s*)+)\}",
        lambda match: r"\mathrm{" + _compact_letters(match.group(1)) + "}",
        cleaned,
    )

    projection_with_star = re.compile(
        r"P\s*_\s*\{\s*(?P<vec>\\(?:mathbf|bf)\s*\{\s*g\s*\}\s*_\s*\{\s*[^}]+\s*\})\s*"
        r"(?P=vec)\s*\^\s*\{\s*\*\s*\}\s*\}"
    )
    cleaned = projection_with_star.sub(
        lambda match: f"P _ {{ {match.group('vec')} }} {match.group('vec')} ^ {{ * }}",
        cleaned,
    )

    projection_without_star = re.compile(
        r"P\s*_\s*\{\s*(?P<vec>\\(?:mathbf|bf)\s*\{\s*g\s*\}\s*_\s*\{\s*[^}]+\s*\})\s*"
        r"(?P=vec)\s*\}"
    )
    cleaned = projection_without_star.sub(
        lambda match: f"P _ {{ {match.group('vec')} }} {match.group('vec')}",
        cleaned,
    )

    cleaned = cleaned.replace(". $", " .$")
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _compact_letters(text: str) -> str:
    return "".join(text.split())


def _is_equation_item(item: dict[str, Any]) -> bool:
    return item.get("type") == "equation" or item.get("text_format") == "latex"


def _extract_bbox(item: dict[str, Any]) -> list[float]:
    raw_bbox = item.get("bbox")
    if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
        return []

    normalized_bbox: list[float] = []
    for value in raw_bbox:
        if isinstance(value, (int, float)):
            normalized_bbox.append(float(value))
            continue

        if isinstance(value, str):
            try:
                normalized_bbox.append(float(value))
                continue
            except ValueError:
                return []

        return []

    return normalized_bbox


def _is_suspicious_equation(text: str) -> bool:
    formula = text.strip()
    if formula.startswith("$$") and formula.endswith("$$"):
        formula = formula[2:-2].strip()

    if not formula:
        return True

    if formula.count("{") != formula.count("}"):
        return True

    if formula.count("(") != formula.count(")"):
        return True

    for pattern in SUSPICIOUS_LATEX_PATTERNS:
        if pattern.search(formula):
            return True

    return False


def _extract_source_image_path(item: dict[str, Any]) -> str:
    raw_path = item.get("img_path")
    if isinstance(raw_path, str):
        return raw_path.strip()

    return ""


def _collect_equation_image_paths(content_items: list[dict[str, Any]]) -> set[str]:
    return {
        image_path
        for item in content_items
        if isinstance(item, dict)
        for image_path in [_extract_source_image_path(item)]
        if image_path
    }
