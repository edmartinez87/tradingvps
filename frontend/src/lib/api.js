import axios from "axios";

export const BACKEND = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND}/api`;
export const http = axios.create({ baseURL: API, timeout: 90000 });
// One shared client: the active bot (crypto → /api, HotForex → /api/fx) switches the base URL so every panel is reusable.
export const setApiBase = (bot) => { http.defaults.baseURL = bot === "fx" ? `${BACKEND}/api/fx` : API; };

const TOKEN_KEY = "bot_token";
export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t) => (t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY));

http.interceptors.request.use((cfg) => {
  const t = getToken();
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});
http.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401 && !String(err.config?.url).includes("/auth/")) {
      setToken(null);
      window.dispatchEvent(new Event("auth:logout"));
    }
    return Promise.reject(err);
  },
);

const num = (v, d) =>
  Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

export const fmtUsd = (v, d = 2) => (v == null ? "—" : `$${num(v, d)}`);
export const fmtSignedUsd = (v, d = 2) =>
  v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "-" : ""}$${num(Math.abs(v), d)}`;
export const fmtPct = (v, d = 2) => (v == null ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(d)}%`);
export const fmtPrice = (v) => {
  if (v == null) return "—";
  const n = Number(v);
  const d = n >= 1000 ? 2 : n >= 10 ? 3 : n >= 1 ? 4 : 5;
  return num(n, d);
};
export const fmtQty = (v) => (v == null ? "—" : Number(v).toPrecision(4));
export const fmtTime = (iso) =>
  iso ? new Date(iso).toLocaleTimeString("es-ES", { hour12: false }) : "—";
export const fmtDateTime = (iso) =>
  iso
    ? new Date(iso).toLocaleString("es-ES", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false })
    : "—";
export const pnlClass = (v) => (v > 0 ? "text-emerald-400" : v < 0 ? "text-rose-400" : "text-slate-400");

export const STRATEGY_LABELS = {
  all: "Multi-estrategia",
  trend_ema: "Tendencia EMA",
  mean_reversion: "Reversión a la media",
  breakout_turtle: "Ruptura Turtle",
  supertrend_momentum: "Supertrend + momentum",
  ema_pullback: "Pullback EMA21",
  news_event: "Noticia macro",
};
export const STRATEGY_KEYS = ["trend_ema", "mean_reversion", "breakout_turtle", "supertrend_momentum", "ema_pullback"];
export const MODE_LABELS = { strict: "Estrictos", relaxed: "Relajados", minimal: "Mínimos" };
export const activeStrategies = (s) => (s.strategy === "all" ? STRATEGY_KEYS.filter((k) => !(s.disabled_strategies || []).includes(k)) : [s.strategy]);
export const REASON_LABELS = { TP: "Take Profit", SL: "Stop Loss", TRAILING: "Trailing", MANUAL: "Manual", TIEMPO: "Tiempo máx.", FIN_SEMANA: "Fin de semana" };
export const errMsg = (e) => {
  const d = e?.response?.data?.detail;
  if (Array.isArray(d)) return `Valor inválido en: ${d.map((x) => x.loc?.slice(-1)[0]).join(", ")}`;
  return d || e?.message || "Error";
};
