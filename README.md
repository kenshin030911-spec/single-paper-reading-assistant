# 单篇论文精读助手

一个面向**单篇论文**场景的小型全栈 AI 应用,支持 PDF 上传、论文结构化解析、精读分析、多轮问答，以及复杂公式的 LaTeX 渲染与图片 fallback 展示。
它会先用 MinerU 解析上传的 PDF，再用本地 Ollama 生成结构化精读分析和基于当前论文的问答结果。
---

## 项目定位

这个项目不做通用知识库，也不做多论文管理，而是专注于：

- 对**单篇论文**进行结构化解析
- 结合本地大模型生成精读分析
- 支持围绕当前论文的多轮问答
- 在复杂公式场景下提供更稳定的展示体验
- 对重复上传的同一篇 PDF 进行解析结果复用，避免重复跑 MinerU

---

## 前端页面展示
文献上传区
<img width="1421" height="774" alt="e68f7b2fc5c4bbf57091cf515a485d5d" src="https://github.com/user-attachments/assets/a303bb0c-e1a5-45a5-93e9-670c89840560" />
解析展示区
<img width="1348" height="870" alt="41baa87186596c97061bac6aa038d1e2" src="https://github.com/user-attachments/assets/bcbd171f-baf1-4ce8-b48d-8fc3d977958e" />
精读分析与问答区
<img width="1345" height="897" alt="1f77a9cee9adb9644f1d8d858f9a095d" src="https://github.com/user-attachments/assets/9603686e-bc39-4575-bf67-88e5db13ab81" />

---

## 核心功能

### 1. PDF 上传与结构化解析
- 前端上传论文 PDF
- 后端调用 MinerU 完成结构化解析
- 抽取标题、摘要、章节、正文片段与公式块
- 解析结果组织为：
  - `title`
  - `abstract`
  - `sections`
  - `content`
  - `blocks`

### 2. 解析缓存
- 上传时先对 PDF 文件内容计算 **SHA-256**
- 若命中 `backend/data/parse_cache/<pdf_sha256>/`
  - 直接复用缓存里的 `paper_content.json`
  - 恢复 `source.pdf` 和 `mineru_assets/`
  - 跳过 MinerU
- 若未命中
  - 走正常 MinerU 解析流程
  - 成功后把结果写入解析缓存
- 这样同一篇 PDF 二次上传时可以显著缩短时间，即使前后端或 IDE 重启后也仍可命中缓存（只要缓存目录未被删除）

### 3. 当前会话缓存
系统仍保留当前单篇论文工作流所需的运行时缓存：

- `current_paper.json`：当前论文的结构化结果
- `current_analysis.json`：当前论文最近一次分析结果
- `current_section_embeddings.json`：当前论文的 section embeddings
- `papers/`：当前会话的 PDF
- `mineru_assets/`：当前会话的 MinerU 资产
- `equations/`：公式截图缓存

### 4. 精读分析
- 基于本地 Ollama + `deepseek-r1:8b`
- 生成研究问题、研究动机、核心思想、方法主线、关键概念、实验逻辑、亮点、局限与阅读重点等结构化结果

### 5. 论文问答
- 不再直接把整篇论文压缩后统一送给模型
- 先做 **section 级 embeddings 路由**
- 再在命中 section 内做 **block 级精排**
- 对公式问题优先补充 equation block 及前后 text block

### 6. 公式展示优化
- 对正常 LaTeX 进行 KaTeX 渲染
- 对疑似损坏公式提供 PDF 区域截图 fallback

### 7. 上传链路日志可观测性
上传时后端终端会输出关键状态，便于观察缓存是否生效：

- `HIT`：命中解析缓存，跳过 MinerU
- `MISS`：未命中缓存，开始跑 MinerU
- `INVALID_FALLBACK`：缓存损坏、版本不兼容或恢复失败，已删除缓存并回退到 MinerU
- `SAVE`：新解析结果成功写回缓存
- `SAVE_FAILED`：缓存写回失败，但不影响本次上传主流程

---

## 技术栈

### 前端
- React
- Vite
- KaTeX
- ReactMarkdown

### 后端
- FastAPI
- Pydantic
- Ollama
- MinerU
- PyMuPDF
- Pillow

### 本地模型
- `deepseek-r1:8b`：精读分析与问答
- `embeddinggemma`：section embeddings

---

## 运行环境

- Python 3.11
- Node.js 18+
- 已安装并可运行的 Ollama

---

## 本地运行步骤

### 1. 安装后端依赖

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. 启动 Ollama

确保 Ollama 服务已启动，并且上面的两个模型已经下载。

默认后端会连接：

```text
http://127.0.0.1:11434
```

如果你用了其他地址，可以通过环境变量覆盖：

```powershell
$env:OLLAMA_BASE_URL="http://127.0.0.1:11434"
```

### 3. 启动后端

```bash
cd backend
python -m uvicorn app.main:app --reload
```

默认后端地址：
- `http://127.0.0.1:8000`

### 4. 启动前端

```bash
cd frontend
npm install
npm run dev
```

默认前端地址：
- `http://127.0.0.1:5173`

---

## 使用流程

1. 在前端页面上传 PDF
2. 等待 MinerU 完成解析
3. 点击生成精读分析
4. 继续基于当前论文提问

说明：

- 第一次上传一篇新 PDF 时，MinerU 解析可能需要几分钟
- 第二次上传同一篇 PDF 时，如果 `backend/data/parse_cache/` 中缓存仍在，后端会直接命中解析缓存并跳过 MinerU
- 上传命中解析缓存后，仍可能继续花几秒到几十秒生成 section embeddings；这是当前版本的正常行为

---

## 系统结构

```text
frontend/
  src/
    App.jsx
    main.jsx
    api/paper.js
    components/
      UploadForm.jsx
      PaperResult.jsx
      AnalysisPanel.jsx
      AskPanel.jsx
      MathText.jsx
    styles.css

backend/
  app/
    main.py
    api/routes/
      upload.py
      analyze.py
      ask.py
      equation_image.py
    schemas/
      paper.py
      reading.py
    services/
      mineru_parser.py
      paper_store.py
      ollama_client.py
      reading_service.py
      section_router.py
      equation_image_service.py
  data/
    current_paper.json
    current_analysis.json
    current_section_embeddings.json
    parse_cache/
      <pdf_sha256>/
        meta.json
        paper_content.json
        source.pdf
        mineru_assets/
    papers/
    equations/
    mineru_assets/
```

---

## 主要数据流

### 1. 上传 PDF

```text
上传 PDF
  -> /upload
  -> 计算 PDF 内容 SHA-256
  -> 检查 parse_cache/<sha256>/
      -> HIT：恢复缓存结果，跳过 MinerU
      -> MISS：调用 MinerU 解析
      -> INVALID_FALLBACK：删除坏缓存并回退到 MinerU
  -> 保存 current_paper.json
  -> 尝试生成 current_section_embeddings.json
  -> 前端展示论文解析结果
```

### 2. 生成精读分析

```text
点击“生成精读分析”
  -> /analyze
  -> 读取 current_paper.json
  -> 组织论文上下文
  -> 调用 Ollama 生成结构化分析
  -> 保存 current_analysis.json
  -> 前端展示分析结果
```

### 3. 论文问答

```text
提问
  -> /ask
  -> 读取 current_paper.json
  -> section embeddings 路由 top-k sections
  -> 在命中 section 内 block 精排
  -> 组织聚焦上下文
  -> 调用 Ollama 生成回答
  -> 前端展示问答结果
```

### 4. 公式截图 fallback

```text
前端发现公式可疑或渲染失败
  -> /equation-image/{paper_id}/{equation_id}.png
  -> 后端读取当前 PDF 和 MinerU 资产
  -> 裁剪或恢复公式区域图片
  -> 返回 PNG 给前端
```

---

## 当前已知限制

1. **MinerU 对复杂公式的文本识别并不总是稳定**
   - 当前已通过图片 fallback 缓解展示问题
   - 但公式文本本身的损坏仍可能影响问答质量

2. **精读分析仍以整篇概览为主**
   - ask 的路由效果已明显增强
   - analyze 仍有继续做“关键 section 深讲”的空间

3. **项目当前只支持单篇论文工作流**
   - 适合精读场景
   - 不适合多论文知识库管理

4. **本地模型能力受硬件与模型规模限制**
   - 使用 `deepseek-r1:8b` 可满足本地验证
   - 但在极复杂问题上仍可能不如云端大模型

5. **解析缓存已做，但 embeddings 仍未做跨上传复用**
   - 重复上传时可跳过 MinerU
   - 但不一定实现“秒回上传”

---

## 已做的关键优化

- 从 mock 上传闭环逐步演化为真实 PDF 解析链路
- 从纯文本 section 摘要升级为 `summary + content + blocks`
- 为复杂公式增加 LaTeX 渲染与图片 fallback
- 为问答增加 section embeddings 路由与 block 级精排
- 为重复上传增加 **按 PDF SHA-256 命中的磁盘解析缓存**
- 为上传链路增加可观测日志，便于判断缓存命中与回退状态

---

## 实验结论（当前阶段）

我对 2 篇论文进行了小规模人工评测，每篇论文设置 4 个问题，并比较了 3 种问答模式：

- `global`：整篇统一压缩上下文
- `section_only`：section 路由
- `full`：section 路由 + block 精排

### 主要观察

1. **section 路由相较 global 基线有稳定提升**
   - 在方法、实验、贡献类问题上，`section_only` 和 `full` 都显著优于 `global`
   - 说明“整篇压缩后统一送模型”不是单篇论文问答的最佳策略

2. **full 总体最好，但相比 section_only 提升有限**
   - 当前收益主要来自 **section 级路由**
   - block 级精排带来的额外提升相对较小

3. **block 精排对公式类问题的收益暂时不稳定**
   - 当前公式类问题更多是“变量定义/参数作用解释题”
   - 对这类问题，只要 section 命中正确，`section_only` 已经能给出较好的回答
   - `full` 的局部公式窗口有时会更细，但不一定更准

4. **当前 equation window 仍偏窄**
   - 现在采用“前 1 个 text block + 当前 equation block + 后 1 个 text block”
   - 对局部解释题有效
   - 但如果变量定义和背景分散在整节，局部窗口可能仍不够

### 当前可支持的结论

- **section 路由明确提升了单篇论文问答质量**
- **block 精排是有潜力的，但当前实现下对公式相关问题的收益仍不稳定**

---

## 后续可继续优化的方向

1. 为 ask 增加更稳定的变量/公式解释模式
2. 为 analyze 增加“关键章节深讲”
3. 为 section embeddings 增加 `pdf_sha256` 级别缓存
4. 扩大公式相关问题的局部上下文窗口

