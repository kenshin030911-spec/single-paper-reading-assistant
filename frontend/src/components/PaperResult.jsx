import MathText from "./MathText";


function PaperResult({ paperData }) {
  if (!paperData) {
    return (
      <section className="result-card empty-state">
        <h2>MinerU 解析结果</h2>
        <p>上传 PDF 后，这里会展示论文标题、摘要和 sections 列表。</p>
      </section>
    );
  }

  return (
    <section className="result-card panel-card">
      <div className="panel-header">
        <div>
          <p className="panel-eyebrow">MinerU Parse</p>
          <h2>MinerU 解析结果</h2>
          <p className="panel-text">
            这一部分直接来自 PDF 解析与清洗结果，是后续精读分析和问答的底层上下文。
          </p>
        </div>
      </div>

      <div className="content-block">
        <h2>论文标题</h2>
        <p className="paper-title">{paperData.title}</p>
      </div>

      <div className="content-block">
        <h2>摘要</h2>
        <MathText text={paperData.abstract} />
      </div>

      <div className="content-block">
        <h2>Sections</h2>
        <ul className="section-list">
          {paperData.sections.map((section, index) => {
            const hasBlocks = Array.isArray(section.blocks) && section.blocks.length > 0;
            const hasExpandedContent = hasBlocks || (section.content && section.content !== section.summary);

            return (
            <li key={`${index}-${section.heading}`} className="section-item">
              <h3>{section.heading}</h3>
              <MathText text={section.summary} />

              {hasExpandedContent && (
                <details className="section-details">
                  <summary>展开更完整内容</summary>
                  {hasBlocks ? (
                    <MathText
                      blocks={section.blocks}
                      paperId={paperData.paper_id}
                      className="section-content"
                    />
                  ) : section.content ? (
                    <MathText text={section.content} className="section-content" />
                  ) : (
                    <MathText text={section.summary} className="section-content" />
                  )}
                </details>
              )}
            </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}


export default PaperResult;
