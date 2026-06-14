import { useEffect, useState } from "react";
import api from "../api";

function Header({ selectedSymbol, onSelectInstrument }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [authenticated, setAuthenticated] = useState(false);
  const [marketStatus, setMarketStatus] = useState(null);

  useEffect(() => {
    const checkAuth = async () => {
      try {
        const res = await api.get("/token-status");
        setAuthenticated(res.data.authenticated);
      } catch {
        setAuthenticated(false);
      }
    };

    const checkMarket = async () => {
      try {
        const res = await api.get("/api/market-status");
        setMarketStatus(res.data.data);
      } catch {
        setMarketStatus(null);
      }
    };

    checkAuth();
    checkMarket();
    const interval = setInterval(checkMarket, 60000);
    return () => clearInterval(interval);
  }, []);

  const handleSearch = async (value) => {
    setQuery(value);
    if (value.trim().length < 2) {
      setResults([]);
      return;
    }

    try {
      const res = await api.get("/api/search", { params: { q: value, exchange: "NSE" } });
      setResults(res.data.results || []);
    } catch {
      setResults([]);
    }
  };

  const handleSelect = (item) => {
    onSelectInstrument({
      instrument_key: item.instrument_key,
      symbol: item.trading_symbol || item.symbol || item.name,
    });
    setQuery("");
    setResults([]);
  };

  const connectUpstox = async () => {
    try {
      const res = await api.get("/login");
      window.open(res.data.auth_url, "_blank");
    } catch {
      // ignore
    }
  };

  return (
    <header className="header">
      <div className="header-brand">
        <span className="logo">MarketPulse Pro</span>
        {selectedSymbol && <span className="selected-symbol">{selectedSymbol}</span>}
      </div>

      <div className="header-search">
        <input
          type="text"
          placeholder="Search symbol (e.g. RELIANCE, TCS)"
          value={query}
          onChange={(e) => handleSearch(e.target.value)}
        />
        {results.length > 0 && (
          <ul className="search-results">
            {results.map((item) => (
              <li key={item.instrument_key} onClick={() => handleSelect(item)}>
                <span className="result-symbol">{item.trading_symbol || item.symbol}</span>
                <span className="result-name">{item.name}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="header-status">
        {marketStatus && (
          <span className={`badge ${marketStatus.status === "NORMAL_OPEN" ? "badge-open" : "badge-closed"}`}>
            {marketStatus.status || "UNKNOWN"}
          </span>
        )}
        <button className={`auth-btn ${authenticated ? "connected" : ""}`} onClick={connectUpstox}>
          {authenticated ? "Upstox Connected" : "Connect Upstox"}
        </button>
      </div>
    </header>
  );
}

export default Header;
