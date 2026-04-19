from typing import Literal

from pydantic import BaseModel, Field


class SectionBlock(BaseModel):
    # section 内部的轻量内容块，主要用来保留 equation 元数据和前端展示顺序。
    block_type: Literal["text", "equation"] = Field(..., description="内容块类型")
    text: str = Field(..., description="块文本内容")
    equation_id: str = Field("", description="公式块唯一 ID")
    source_image_path: str = Field("", description="MinerU 原始公式图片相对路径")
    page_idx: int | None = Field(default=None, description="公式所在页码，从 0 开始")
    bbox: list[float] = Field(default_factory=list, description="公式在 PDF 页面中的 bbox")
    is_suspicious: bool = Field(False, description="公式文本是否疑似损坏")


class Section(BaseModel):
    # 单个章节的展示结构。
    heading: str = Field(..., description="章节标题")
    summary: str = Field(..., description="章节摘要")
    content: str = Field("", description="章节更完整的正文片段")
    blocks: list[SectionBlock] = Field(default_factory=list, description="章节内容块列表")


class PaperContent(BaseModel):
    # 论文的基础结构化内容，来自 MinerU 解析和清洗。
    title: str = Field(..., description="论文标题")
    abstract: str = Field(..., description="论文摘要")
    sections: list[Section] = Field(default_factory=list, description="章节列表")


class PaperRecord(PaperContent):
    # 当前缓存中的单篇论文结构，同时也作为上传接口响应返回给前端。
    paper_id: str = Field(..., description="当前论文唯一标识")
