from app.schemas.paper import PaperRecord
from app.schemas.reading import AskEvalMode, AskResponse, ChatMessage, PaperAnalysis, PaperAnalysisResponse
from app.services.ollama_client import generate_structured_output, generate_text_response
from app.services.paper_store import (
    load_current_analysis,
    load_current_paper,
    save_current_analysis,
)
from app.services.section_router import (
    FocusedAskContext,
    SectionRoutingError,
    build_focused_ask_context,
    build_section_only_ask_context,
    is_formula_question,
)


MAX_HISTORY_MESSAGES = 6
MAX_CONTEXT_SECTIONS = 12
MAX_SECTION_CONTEXT_CHARS = 900
MAX_TOTAL_CONTEXT_CHARS = 7000


class ReadingServiceError(RuntimeError):
    """精读分析与问答流程中的业务异常。"""


def analyze_current_paper(paper_id: str) -> PaperAnalysisResponse:
    """优先返回分析缓存；没有缓存时，再调用 Ollama 生成新的精读分析。"""
    cached_analysis = load_current_analysis(paper_id)
    if cached_analysis is not None:
        return cached_analysis

    paper = load_current_paper(paper_id)
    paper_context = _build_paper_context(paper)

    system_prompt = (
        "你是一个单篇论文精读助手。"
        "你的任务不是简单摘要，而是像组会前的论文助教一样做结构化讲解。"
        "请尽量解释论文为什么值得看、核心思路怎么串起来、实验到底在证明什么。"
        "不要捏造论文中没有出现的实验结论，也不要输出思考过程。"
    )
    user_prompt = (
        "请基于下面的论文内容，输出结构化精读讲解。\n"
        "要求：\n"
        "1. 所有字段都尽量填写，但不要臆造。\n"
        "2. method_pipeline 用 4-6 步列表写清楚方法主线。\n"
        "3. key_concepts 每项都包含 term 和 explanation，优先挑新手真正会卡住的术语。\n"
        "4. strengths、weaknesses、reading_focus、confusing_points 都用 3-5 条列表表达。\n"
        "5. experiment_logic 要讲清楚实验想验证什么，而不是只罗列结果。\n"
        "6. 如果当前解析内容不足以确认，请明确写“从当前解析内容无法完全确认”。\n\n"
        f"{paper_context}"
    )

    analysis = generate_structured_output(system_prompt, user_prompt, PaperAnalysis)
    analysis_response = PaperAnalysisResponse(
        paper_id=paper.paper_id,
        **analysis.model_dump(),
    )
    save_current_analysis(analysis_response)
    return analysis_response


def ask_about_current_paper(
    paper_id: str,
    question: str,
    chat_history: list[ChatMessage],
    eval_mode: AskEvalMode = "full",
) -> AskResponse:
    """基于当前论文缓存做多轮问答，不重新解析 PDF。"""
    paper = load_current_paper(paper_id)
    trimmed_history = chat_history[-MAX_HISTORY_MESSAGES:]

    try:
        focused_context = _build_temp_ablation_ask_context(
            paper=paper,
            question=question,
            eval_mode=eval_mode,
        )
    except SectionRoutingError as exc:
        raise ReadingServiceError(str(exc)) from exc

    system_prompt = (
        "你是一个单篇论文精读助手。"
        "你只能基于当前给出的聚焦上下文回答问题。"
        "回答要直接、清楚、基于证据。"
        "如果这是公式、推导、约束或变量相关问题，请先说明相关公式或定理在论文中的作用，"
        "再解释关键变量、约束或前后关系，最后用自然语言总结。"
        "如果信息仍不足，不要只说“无法确认”，要说明当前上下文缺了什么。"
        "不要输出思考过程或标签。"
    )
    user_prompt = (
        "下面是围绕用户问题筛选后的论文聚焦上下文：\n"
        f"{focused_context.context}\n\n"
        f"问题类型：{'公式相关问题' if focused_context.is_formula_question else '普通阅读问题'}\n\n"
        f"用户问题：{question}\n\n"
        "请基于证据回答，不要脱离给定上下文扩展。"
    )
    answer = generate_text_response(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        chat_history=[message.model_dump() for message in trimmed_history],
    )

    return AskResponse(
        paper_id=paper.paper_id,
        question=question,
        answer=answer,
        used_mode=eval_mode,
        matched_sections=focused_context.matched_headings,
    )


def _build_temp_ablation_ask_context(
    *,
    paper: PaperRecord,
    question: str,
    eval_mode: AskEvalMode,
) -> FocusedAskContext:
    """
    TEMP/ABLATION：本地评测 ask 上下文开关。
    只比较上下文构造策略，不改 prompt 主体和模型调用链路。
    """
    if eval_mode == "global":
        return FocusedAskContext(
            context=_build_paper_context(paper),
            matched_headings=[],
            is_formula_question=is_formula_question(question),
        )

    if eval_mode == "section_only":
        return build_section_only_ask_context(paper, question)

    return build_focused_ask_context(paper, question)


def _build_paper_context(paper: PaperRecord) -> str:
    """把当前论文缓存拼成一段易于传给 LLM 的上下文。"""
    lines = [
        f"论文标题：{paper.title}",
        f"论文摘要：{paper.abstract}",
        "",
        "论文章节内容：",
    ]
    used_chars = sum(len(line) for line in lines)

    for index, section in enumerate(paper.sections[:MAX_CONTEXT_SECTIONS], start=1):
        section_text = _select_section_context(section)
        remaining_chars = MAX_TOTAL_CONTEXT_CHARS - used_chars
        if remaining_chars <= 120:
            break

        section_text = _truncate_text(section_text, min(MAX_SECTION_CONTEXT_CHARS, remaining_chars))
        lines.append(f"{index}. {section.heading}")
        lines.append(f"   内容片段：{section_text}")
        used_chars += len(lines[-2]) + len(lines[-1])

    return "\n".join(lines)


def _select_section_context(section) -> str:
    content = section.content.strip()
    if content:
        return content

    return section.summary.strip()


def _truncate_text(text: str, max_chars: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned

    return f"{cleaned[:max_chars].rstrip()}..."
