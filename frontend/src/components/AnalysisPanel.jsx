import MathText from "./MathText";


function AnalysisPanel({
  paperId,
  analysisData,
  isAnalyzing,
  errorMessage,
  onAnalyze,
}) {
  return (
    <section className="result-card panel-card">
      <div className="panel-header">
        <div>
          <p className="panel-eyebrow">Ollama Analysis</p>
          <h2>精读分析</h2>
          <p className="panel-text">
            这一部分由本地 Ollama 模型 `deepseek-r1:8b` 生成，不会重新解析 PDF。
          </p>
        </div>

        <button
          type="button"
          className="action-button"
          onClick={onAnalyze}
          disabled={!paperId || isAnalyzing}
        >
          {isAnalyzing ? "分析生成中..." : "生成精读分析"}
        </button>
      </div>

      {!paperId && (
        <p className="panel-placeholder">请先上传并解析一篇论文，再生成精读分析。</p>
      )}

      {errorMessage && <p className="panel-error">{errorMessage}</p>}

      {paperId && !analysisData && !errorMessage && (
        <p className="panel-placeholder">
          当前还没有分析结果。点击上方按钮后，后端会读取 `current_paper.json` 并调用 Ollama 生成分析。
        </p>
      )}

      {analysisData && (
        <div className="analysis-layout">
          <section className="analysis-hero">
            <span className="analysis-chip">精读讲解</span>
            <h3>论文概览</h3>
            <MathText text={analysisData.paper_overview} />
          </section>

          <div className="analysis-summary-grid">
            <section className="analysis-block">
              <h3>研究问题</h3>
              <MathText text={analysisData.research_problem} />
            </section>

            <section className="analysis-block">
              <h3>研究动机</h3>
              <MathText text={analysisData.motivation} />
            </section>

            <section className="analysis-block analysis-block-wide">
              <h3>核心思想</h3>
              <MathText text={analysisData.core_idea} />
            </section>
          </div>

          <section className="analysis-block">
            <h3>方法主线</h3>
            <ol className="analysis-step-list">
              {analysisData.method_pipeline.map((item, index) => (
                <li key={`${index}-${item}`} className="analysis-step-item">
                  <span className="analysis-step-index">{index + 1}</span>
                  <MathText text={item} />
                </li>
              ))}
            </ol>
          </section>

          <section className="analysis-block">
            <h3>关键概念</h3>
            <div className="concept-grid">
              {analysisData.key_concepts.map((concept) => (
                <article key={concept.term} className="concept-card">
                  <h4>{concept.term}</h4>
                  <MathText text={concept.explanation} />
                </article>
              ))}
            </div>
          </section>

          <div className="analysis-summary-grid">
            <section className="analysis-block">
              <h3>实验逻辑</h3>
              <MathText text={analysisData.experiment_logic} />
            </section>

            <section className="analysis-block">
              <h3>亮点</h3>
              <ul className="bullet-list">
                {analysisData.strengths.map((item, index) => (
                  <li key={`${index}-${item}`}>
                    <MathText text={item} />
                  </li>
                ))}
              </ul>
            </section>

            <section className="analysis-block">
              <h3>局限性</h3>
              <ul className="bullet-list">
                {analysisData.weaknesses.map((item, index) => (
                  <li key={`${index}-${item}`}>
                    <MathText text={item} />
                  </li>
                ))}
              </ul>
            </section>
          </div>

          <div className="analysis-summary-grid">
            <section className="analysis-block">
              <h3>阅读重点</h3>
              <ul className="bullet-list">
                {analysisData.reading_focus.map((item, index) => (
                  <li key={`${index}-${item}`}>
                    <MathText text={item} />
                  </li>
                ))}
              </ul>
            </section>

            <section className="analysis-block">
              <h3>易卡点</h3>
              <ul className="bullet-list">
                {analysisData.confusing_points.map((item, index) => (
                  <li key={`${index}-${item}`}>
                    <MathText text={item} />
                  </li>
                ))}
              </ul>
            </section>
          </div>
        </div>
      )}
    </section>
  );
}


export default AnalysisPanel;
