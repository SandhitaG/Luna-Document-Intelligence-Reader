import React, { useState } from 'react';

const PDFViewer = ({ onResult }) => {
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [loading, setLoading] = useState(false);

  const handleFileChange = (e) => {
    setSelectedFiles(Array.from(e.target.files));
  };

  const handleUpload = async () => {
    if (!selectedFiles.length) {
      alert("❗ Please select at least one PDF file.");
      return;
    }

    setLoading(true);

    try {
      // Step 1: Upload PDFs
      const formData = new FormData();
      for (const file of selectedFiles) {
        formData.append("pdfs", file);
      }

      const uploadRes = await fetch("http://localhost:5000/upload", {
        method: "POST",
        body: formData,
      });

      const uploadText = await uploadRes.text();
      let uploadData;
      try {
        uploadData = JSON.parse(uploadText);
      } catch {
        throw new Error("❌ Upload response is not valid JSON: " + uploadText);
      }

      if (!uploadRes.ok) throw new Error(uploadData.error || "Upload failed");

      // Step 2: Trigger processing
      const processRes = await fetch("http://localhost:5000/process", {
        method: "POST",
      });

      const processText = await processRes.text();
      let processData;
      try {
        processData = JSON.parse(processText);
      } catch {
        throw new Error("❌ Process response is not valid JSON: " + processText);
      }

      if (!processRes.ok) throw new Error(processData.error || "Processing failed");

      // Step 3: Parse output (must be JSON string from backend)
      let finalOutput;
      try {
        finalOutput = JSON.parse(processData.output);
      } catch {
        throw new Error("❌ Output from backend is not valid JSON.");
      }

      // Send final result to parent component
      onResult(finalOutput);

    } catch (error) {
      console.error("Error:", error);
      alert("🚨 " + error.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="pdf-viewer">
      <h2>📄 Document Intelligence Reader</h2>

      <input
        type="file"
        multiple
        accept=".pdf"
        onChange={handleFileChange}
      />

      <button onClick={handleUpload} disabled={loading}>
        {loading ? "⏳ Processing..." : "🚀 Extract"}
      </button>
    </div>
  );
};

export default PDFViewer;
