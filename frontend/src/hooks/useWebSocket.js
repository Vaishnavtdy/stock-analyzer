import { useEffect, useRef, useState } from "react";
import { WS_BASE } from "../api";

/**
 * Connects to the backend /ws/feed websocket and subscribes to the given
 * instrument keys. Returns the latest tick and connection status.
 */
export function useWebSocket(instrumentKeys) {
  const [tick, setTick] = useState(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);

  useEffect(() => {
    if (!instrumentKeys || instrumentKeys.length === 0) {
      return;
    }

    const ws = new WebSocket(`${WS_BASE}/ws/feed`);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      ws.send(JSON.stringify({ instrument_keys: instrumentKeys }));
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setTick(data);
      } catch {
        // ignore malformed messages
      }
    };

    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [JSON.stringify(instrumentKeys)]);

  return { tick, connected };
}

export default useWebSocket;
