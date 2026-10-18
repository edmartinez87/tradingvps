import axios from "axios";

export const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
export const http = axios.create({ baseURL: API, timeout: 60000 });

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
};
export const REASON_LABELS = { TP: "Take Profit", SL: "Stop Loss", TRAILING: "Trailing", MANUAL: "Manual" };
export const errMsg = (e) => {
  const d = e?.response?.data?.detail;
  if (Array.isArray(d)) return `Valor inválido en: ${d.map((x) => x.loc?.slice(-1)[0]).join(", ")}`;
  return d || e?.message || "Error";
};
