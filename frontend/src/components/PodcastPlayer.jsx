import React, { useState } from "react";
import ".styles/app.css"; // optional styling

const PodcastPlayer = ({ sectionText }) => {
  const [audioUrl, setAudioUrl] = useState("");
  const [loading, setLoading] = useState(false);

  const handlePlay = async () => {
    setLoading(true);
    try {
      const res = await fetch("http://localhost:5000/podcast", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ section_text: sectionText }),
      });

      if (!res.ok) {
        throw new Error("Failed to fetch podcast");
      }

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      setAudioUrl(url);
    } catch (err) {
      alert("❌ Podcast generation failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="podcast-player">
      <button className="glow-button" onClick={handlePlay}>🎧 Generate Podcast</button>
      {loading && <p>Generating...</p>}
      {audioUrl && (
        <audio controls src={audioUrl} style={{ marginTop: "10px" }} />
      )}
    </div>
  );
};

export default PodcastPlayer;
