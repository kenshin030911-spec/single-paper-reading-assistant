export async function uploadPdf(file) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch("/api/upload", {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    let errorMessage = "上传失败，请检查后端服务。";

    try {
      const errorData = await response.json();
      errorMessage = errorData.detail || errorMessage;
    } catch {
      // 如果后端没有返回 JSON，这里保留默认错误信息即可。
    }

    throw new Error(errorMessage);
  }

  return response.json();
}


export async function analyzePaper(paperId) {
  const response = await fetch("/api/analyze", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ paper_id: paperId }),
  });

  if (!response.ok) {
    let errorMessage = "生成精读分析失败，请检查 Ollama 服务。";

    try {
      const errorData = await response.json();
      errorMessage = errorData.detail || errorMessage;
    } catch {
      // 保留默认错误信息即可。
    }

    throw new Error(errorMessage);
  }

  return response.json();
}


export async function askPaper({ paperId, question, chatHistory = [] }) {
  const response = await fetch("/api/ask", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      paper_id: paperId,
      question,
      chat_history: chatHistory,
    }),
  });

  if (!response.ok) {
    let errorMessage = "论文问答失败，请检查 Ollama 服务。";

    try {
      const errorData = await response.json();
      errorMessage = errorData.detail || errorMessage;
    } catch {
      // 保留默认错误信息即可。
    }

    throw new Error(errorMessage);
  }

  return response.json();
}
