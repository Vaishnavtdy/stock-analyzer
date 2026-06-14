import useAI from "../hooks/useAI";

function AIAnalyst({ analysis }) {
  const { analysis: narrative, loading, error, fetchAnalysis } = useAI();

  return (
    <div className="panel ai-analyst">
      <div className="ai-header">
        <h3>AI Analyst</h3>
        <button onClick={() => fetchAnalysis(analysis)} disabled={!analysis || loading}>
          {loading ? "Thinking..." : "Get AI Take"}
        </button>
      </div>

      {error && <div className="ai-error">{error}</div>}
      {narrative && <p className="ai-narrative">{narrative}</p>}
      {!narrative && !loading && !error && (
        <p className="ai-placeholder">Run an analysis, then click "Get AI Take" for a plain-language summary.</p>
      )}
    </div>
  );
}

export default AIAnalyst;
