# 单篇论文精读助手流程图

下面的流程图基于当前项目代码整理，采用 Mermaid 语法，适合直接放在 GitHub 或支持 Mermaid 的 Markdown 查看器中阅读。

## 1. 项目总体流程

```mermaid
flowchart LR
    U[用户]

    subgraph FE[前端 React + Vite]
        APP[App.jsx]
        UPLOAD[UploadForm]
        RESULT[PaperResult]
        ANALYSIS[AnalysisPanel]
        ASK[AskPanel]
        MATH[MathText]
    end

    subgraph BE[后端 FastAPI]
        API_UPLOAD["POST /upload"]
        API_ANALYZE["POST /analyze"]
        API_ASK["POST /ask"]
        API_EQ["GET /equation-image/{paper_id}/{equation_id}.png"]
        PARSER[MinerU Parser]
        READING[Reading Service]
        ROUTER[Section Router]
        EQ_SERVICE[Equation Image Service]
        STORE[Paper Store]
    end

    subgraph MODEL[本地模型 / 工具]
        MINERU[MinerU]
        OLLAMA[Ollama]
        EMBED["embeddinggemma"]
        LLM["deepseek-r1:8b"]
    end

    subgraph DATA[本地缓存]
        CURRENT_PAPER["current_paper.json"]
        CURRENT_ANALYSIS["current_analysis.json"]
        CURRENT_EMB["current_section_embeddings.json"]
        PARSE_CACHE["parse_cache/<pdf_sha256>/"]
        PAPERS["papers/<paper_id>.pdf"]
        ASSETS["mineru_assets/<paper_id>/"]
        EQUATIONS["equations/<paper_id>/"]
    end

    U --> UPLOAD
    U --> ANALYSIS
    U --> ASK
    U --> RESULT

    UPLOAD --> APP --> API_UPLOAD
    ANALYSIS --> APP --> API_ANALYZE
    ASK --> APP --> API_ASK
    RESULT --> MATH --> API_EQ

    API_UPLOAD --> PARSER
    API_UPLOAD --> STORE
    API_ANALYZE --> READING
    API_ASK --> READING
    READING --> ROUTER
    API_EQ --> EQ_SERVICE

    PARSER --> MINERU
    READING --> OLLAMA
    ROUTER --> EMBED
    OLLAMA --> LLM

    STORE --> CURRENT_PAPER
    STORE --> CURRENT_ANALYSIS
    STORE --> CURRENT_EMB
    STORE --> PARSE_CACHE
    STORE --> PAPERS
    STORE --> ASSETS
    EQ_SERVICE --> EQUATIONS
```

## 2. 上传、解析与缓存流程

```mermaid
flowchart TD
    A[前端上传 PDF] --> B["POST /upload"]
    B --> C[校验文件名与 .pdf 后缀]
    C --> D[流式计算 PDF SHA-256]
    D --> E{parse_cache 命中?}

    E -->|命中| F[读取 paper_content.json]
    F --> G[恢复 source.pdf 到 papers/]
    G --> H[恢复 mineru_assets 到当前会话目录]
    H --> I[生成新的 paper_id]
    I --> J[写入 current_paper.json]
    J --> K["best-effort 生成 / 读取 section embeddings"]
    K --> L[返回 PaperRecord 给前端]

    E -->|未命中| M[调用 parse_pdf_with_mineru]
    M --> N[保存上传 PDF 到临时目录]
    N --> O[调用 MinerU CLI]
    O --> P[读取 content_list.json]
    P --> Q[提取 title / abstract / sections / blocks]
    Q --> R[缓存当前会话 PDF 到 papers/]
    R --> S[缓存 MinerU 资产到 mineru_assets/]
    S --> T[写入 current_paper.json]
    T --> U[回写 parse_cache]
    U --> K

    F -.缓存损坏或恢复失败.-> V[删除坏缓存]
    V --> M
```

## 3. 精读分析与问答流程

```mermaid
flowchart TD
    A1[用户点击 生成精读分析] --> B1["POST /analyze"]
    B1 --> C1[按 paper_id 读取 current_analysis.json]
    C1 --> D1{分析缓存命中?}
    D1 -->|是| E1[直接返回缓存结果]
    D1 -->|否| F1[读取 current_paper.json]
    F1 --> G1[拼接全论文上下文]
    G1 --> H1["调用 Ollama deepseek-r1:8b 生成结构化分析"]
    H1 --> I1[保存 current_analysis.json]
    I1 --> E1

    A2[用户输入问题] --> B2["POST /ask"]
    B2 --> C2[读取 current_paper.json]
    C2 --> D2[截取最近几轮 chat_history]
    D2 --> E2{eval_mode}
    E2 -->|global| F2[整篇论文上下文]
    E2 -->|section_only| G2[section embeddings top-k 路由]
    E2 -->|full 默认| H2[section embeddings top-k 路由]
    H2 --> I2[按 block 精排]
    I2 --> J2{公式问题?}
    J2 -->|是| K2[优先取 equation block 前后文本窗口]
    J2 -->|否| L2[优先取相关 text snippets]
    G2 --> M2[拼装 section-only 上下文]
    K2 --> N2[拼装 focused context]
    L2 --> N2
    F2 --> O2["调用 Ollama deepseek-r1:8b 生成回答"]
    M2 --> O2
    N2 --> O2
    O2 --> P2[返回 answer + matched_sections]

    H2 --> Q2{section embeddings 已缓存?}
    Q2 -->|是| R2[读取 current_section_embeddings.json]
    Q2 -->|否| S2["调用 embeddinggemma 生成 embeddings"]
    S2 --> T2[写入 current_section_embeddings.json]
    R2 --> I2
    T2 --> I2
```

## 4. 公式渲染与图片 fallback 流程

```mermaid
flowchart TD
    A[前端 MathText 渲染 section.blocks] --> B{当前 block 是公式?}
    B -->|否| C[按普通文本 / Markdown / KaTeX inline 渲染]
    B -->|是| D[检测公式是否可疑]
    D --> E{KaTeX 渲染成功且不疑似损坏?}
    E -->|是| F[直接显示公式]
    E -->|否| G["GET /equation-image/{paper_id}/{equation_id}.png"]

    G --> H[后端定位当前论文与 equation block]
    H --> I{已有 equations PNG 缓存?}
    I -->|是| J[直接返回缓存图片]
    I -->|否| K{MinerU 原始图片路径可用?}
    K -->|是| L[从 mineru_assets 复制并转存 PNG]
    K -->|否| M[从 papers 里的当前 PDF 裁剪 bbox 区域]
    L --> N[写入 equations/<paper_id>/]
    M --> N
    N --> O[返回 PNG]
    O --> P[前端显示截图 fallback]
```

## 5. 代码对应位置

- 上传与解析缓存：`backend/app/api/routes/upload.py`、`backend/app/services/mineru_parser.py`、`backend/app/services/paper_store.py`
- 精读分析与问答：`backend/app/services/reading_service.py`、`backend/app/services/section_router.py`
- 公式截图 fallback：`frontend/src/components/MathText.jsx`、`backend/app/services/equation_image_service.py`
- 前端页面入口：`frontend/src/App.jsx`
