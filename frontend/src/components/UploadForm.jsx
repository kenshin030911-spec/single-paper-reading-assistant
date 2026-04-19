import { useState } from "react";


function UploadForm({ onUpload, isUploading }) {
  const [selectedFile, setSelectedFile] = useState(null);

  const handleFileChange = (event) => {
    const file = event.target.files?.[0] || null;
    setSelectedFile(file);
  };

  const handleSubmit = async (event) => {
    event.preventDefault();

    if (!selectedFile) {
      return;
    }

    await onUpload(selectedFile);
  };

  return (
    <form className="upload-panel" onSubmit={handleSubmit}>
      <label className="upload-field">
        <span>选择 PDF 文件</span>
        <input
          type="file"
          accept="application/pdf,.pdf"
          onChange={handleFileChange}
          disabled={isUploading}
        />
      </label>

      <div className="upload-actions">
        <button type="submit" disabled={!selectedFile || isUploading}>
          {isUploading ? "上传中..." : "上传并解析"}
        </button>
        <p className="file-hint">
          {selectedFile ? `已选择：${selectedFile.name}` : "尚未选择文件"}
        </p>
      </div>
    </form>
  );
}


export default UploadForm;

