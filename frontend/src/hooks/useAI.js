import { useState } from "react";
import api from "../api";

/**
 * Requests an AI-generated narrative summary for the given analysis payload.
 */
export function useAI() {
  const [analysis, setAnalysis] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchAnalysis = async (analysisData) => {
    setLoading(true);
    setError(null);

    try {
      const response = await api.post("/api/ai-analyst", { analysis: analysisData });
      setAnalysis(response.data.analysis);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  };

  return { analysis, loading, error, fetchAnalysis };
}

export default useAI;
