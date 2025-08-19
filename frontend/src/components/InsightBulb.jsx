import React, { useState } from "react";
import ".styles/app.css"; // optional styling

const InsightBulb = ({ sectionText }) => {
  const [insight, setInsight] = useState("");
  const [loading, setLoading] = useState(false);

  const fetchInsight = async () => {
    setLoading(true);
    setInsight("");

    try {
      const res = await fetch("http://localhost:5000/insight", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ section_text: sectionText }),
      });

      const data = await res.json();
      setInsight(data.insight || data.error);
    } catch (err) {
      setInsight("❌ Failed to fetch insight.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="insight-bulb">
      <button className="glow-button" onClick={fetchInsight}>💡 Insight</button>
      {loading && <p>Generating insight...</p>}
      {insight && (
        <div className="insight-box">
          <strong>💬 Insight:</strong>
          <p>{insight}</p>
        </div>
      )}
    </div>
  );
};

export default InsightBulb;
