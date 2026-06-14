import axios from "axios";

export const API_BASE = "http://127.0.0.1:5000";
export const WS_BASE = "ws://127.0.0.1:5000";

export const api = axios.create({
  baseURL: API_BASE,
});

export default api;
