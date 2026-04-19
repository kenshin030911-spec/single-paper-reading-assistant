from typing import Literal

from pydantic import BaseModel, Field


AskEvalMode = Literal["global", "section_only", "full"]


class ChatMessage(BaseModel):
    # 问答接口里保留最近几轮消息，避免引入复杂 memory。
    role: Literal["user", "assistant"] = Field(..., description="消息角色")
    content: str = Field(..., min_length=1, description="消息内容")


class AnalyzeRequest(BaseModel):
    # 生成精读分析时，只需要指定当前 paper_id。
    paper_id: str = Field(..., description="当前论文 ID")


class KeyConcept(BaseModel):
    # 把关键术语拆成 term + explanation，便于前端按“助教讲解”形式展示。
    term: str = Field(..., description="关键术语")
    explanation: str = Field(..., description="术语解释")


class PaperAnalysis(BaseModel):
    # LLM 生成的结构化精读分析内容，更偏“论文助教式讲解”。
    paper_overview: str = Field(..., description="一句话讲清论文整体在做什么")
    research_problem: str = Field(..., description="论文研究问题")
    motivation: str = Field(..., description="为什么值得做")
    core_idea: str = Field(..., description="核心思想")
    method_pipeline: list[str] = Field(default_factory=list, description="方法主线步骤")
    key_concepts: list[KeyConcept] = Field(default_factory=list, description="关键概念解释")
    experiment_logic: str = Field(..., description="实验到底验证了什么")
    strengths: list[str] = Field(default_factory=list, description="主要亮点")
    weaknesses: list[str] = Field(default_factory=list, description="主要局限")
    reading_focus: list[str] = Field(default_factory=list, description="阅读重点")
    confusing_points: list[str] = Field(default_factory=list, description="新手易卡点")


class PaperAnalysisResponse(PaperAnalysis):
    # 对前端返回分析结果时，会附带 paper_id。
    paper_id: str = Field(..., description="当前论文 ID")


class AskRequest(BaseModel):
    # 问答接口输入。chat_history 只保留最近几轮即可。
    paper_id: str = Field(..., description="当前论文 ID")
    question: str = Field(..., min_length=1, description="用户问题")
    chat_history: list[ChatMessage] = Field(default_factory=list, description="最近几轮对话")
    eval_mode: AskEvalMode = Field(
        "full",
        description="TEMP/ABLATION：ask 临时评测模式，默认 full。",
    )


class AskResponse(BaseModel):
    # 问答接口输出。
    paper_id: str = Field(..., description="当前论文 ID")
    question: str = Field(..., description="用户问题")
    answer: str = Field(..., description="模型回答")
    used_mode: AskEvalMode = Field(
        "full",
        description="TEMP/ABLATION：本次 ask 实际使用的评测模式。",
    )
    matched_sections: list[str] = Field(default_factory=list, description="本次问答匹配到的章节标题")
