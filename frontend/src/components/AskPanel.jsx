import { useState } from "react";

import MathText from "./MathText";


function AskPanel({
  paperId,
  qaItems,
  isAsking,
  errorMessage,
  onAsk,
}) {
  const [question, setQuestion] = useState("");

  const handleSubmit = async (event) => {
    event.preventDefault();

    const trimmedQuestion = question.trim();
    if (!trimmedQuestion) {
      return;
    }

    const wasSuccessful = await onAsk(trimmedQuestion);
    if (wasSuccessful) {
      setQuestion("");
    }
  };

  return (
    <section className="result-card panel-card">
      <div className="panel-header">
        <div>
          <p className="panel-eyebrow">Ollama Q&A</p>
          <h2>提问区</h2>
          <p className="panel-text">
            这里会基于当前论文缓存做多轮问答，不会再次调用 MinerU 解析 PDF。
          </p>
        </div>
      </div>

      <form className="qa-form" onSubmit={handleSubmit}>
        <textarea
          className="qa-input"
          rows="4"
          placeholder="例如：这篇论文的核心创新点是什么？实验是否证明了方法有效？"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          disabled={!paperId || isAsking}
        />

        <div className="qa-actions">
          <button type="submit" className="action-button" disabled={!paperId || isAsking}>
            {isAsking ? "回答生成中..." : "提交问题"}
          </button>
        </div>
      </form>

      {!paperId && (
        <p className="panel-placeholder">请先上传并解析一篇论文，再开始提问。</p>
      )}

      {errorMessage && <p className="panel-error">{errorMessage}</p>}

      {paperId && qaItems.length === 0 && !errorMessage && (
        <p className="panel-placeholder">
          当前还没有提问记录。你可以先问论文贡献、方法流程、实验结论或局限性。
        </p>
      )}

      {qaItems.length > 0 && (
        <div className="qa-thread">
          {qaItems.map((item, index) => (
            <article key={`${index}-${item.question}`} className="qa-card">
              <div className="qa-row">
                <span className="qa-role">问题</span>
                <MathText text={item.question} />
              </div>

              <div className="qa-row">
                <span className="qa-role">回答</span>
                <MathText text={item.answer} />
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}


export default AskPanel;
