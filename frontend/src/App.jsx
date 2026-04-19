import { useState } from "react";

import { analyzePaper, askPaper, uploadPdf } from "./api/paper";
import AnalysisPanel from "./components/AnalysisPanel";
import AskPanel from "./components/AskPanel";
import PaperResult from "./components/PaperResult";
import UploadForm from "./components/UploadForm";


function App() {
  const [paperData, setPaperData] = useState(null);
  const [analysisData, setAnalysisData] = useState(null);
  const [qaItems, setQaItems] = useState([]);
  const [statusText, setStatusText] = useState("请选择一个 PDF 文件开始上传。");
  const [isUploading, setIsUploading] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState("");
  const [isAsking, setIsAsking] = useState(false);
  const [askError, setAskError] = useState("");

  const handleUpload = async (file) => {
    setIsUploading(true);
    setStatusText(`正在上传并解析 ${file.name}，首次调用 MinerU 可能需要 1-3 分钟...`);
    setAnalysisData(null);
    setQaItems([]);
    setAnalysisError("");
    setAskError("");

    try {
      const data = await uploadPdf(file);
      setPaperData(data);
      setStatusText("上传成功，当前论文已缓存。现在可以生成精读分析或继续提问。");
    } catch (error) {
      setPaperData(null);
      setAnalysisData(null);
      setQaItems([]);
      setStatusText(error.message || "上传失败，请稍后重试。");
    } finally {
      setIsUploading(false);
    }
  };

  const handleAnalyze = async () => {
    if (!paperData?.paper_id) {
      return;
    }

    setIsAnalyzing(true);
    setAnalysisError("");

    try {
      const data = await analyzePaper(paperData.paper_id);
      setAnalysisData(data);
    } catch (error) {
      setAnalysisError(error.message || "生成精读分析失败。");
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleAsk = async (question) => {
    if (!paperData?.paper_id) {
      return false;
    }

    setIsAsking(true);
    setAskError("");

    const chatHistory = qaItems.slice(-3).flatMap((item) => ([
      { role: "user", content: item.question },
      { role: "assistant", content: item.answer },
    ]));

    try {
      const data = await askPaper({
        paperId: paperData.paper_id,
        question,
        chatHistory,
      });

      setQaItems((previousItems) => [
        ...previousItems,
        { question: data.question, answer: data.answer },
      ]);
      return true;
    } catch (error) {
      setAskError(error.message || "论文问答失败。");
      return false;
    } finally {
      setIsAsking(false);
    }
  };

  return (
    <main className="page-shell">
      <section className="hero-card">
        <div className="hero-copy">
          <p className="eyebrow">Paper Reader</p>
          <h1>单篇论文精读助手</h1>
          <p className="hero-text">
            当前版本会调用 MinerU 解析上传的 PDF，并使用本地 Ollama 生成精读分析和论文问答。
          </p>
        </div>

        <UploadForm onUpload={handleUpload} isUploading={isUploading} />

        <div className="status-box">
          <span className="status-label">上传状态</span>
          <p>{statusText}</p>
        </div>
      </section>

      <PaperResult paperData={paperData} />

      <AnalysisPanel
        paperId={paperData?.paper_id}
        analysisData={analysisData}
        isAnalyzing={isAnalyzing}
        errorMessage={analysisError}
        onAnalyze={handleAnalyze}
      />

      <AskPanel
        paperId={paperData?.paper_id}
        qaItems={qaItems}
        isAsking={isAsking}
        errorMessage={askError}
        onAsk={handleAsk}
      />
    </main>
  );
}


export default App;
