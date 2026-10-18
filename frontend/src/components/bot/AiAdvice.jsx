import { useState } from "react";
import { Sparkles, Loader2, Undo2, CheckCircle2, Info } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { http, errMsg, STRATEGY_LABELS } from "@/lib/api";

const LABELS = {
  symbols: "Pares", strategy: "Estrategia", risk_per_trade: "Riesgo/op (%)", max_positions: "Máx. posiciones", leverage: "Apalancamiento",
  ai_min_confidence: "Confianza mínima IA", trailing_enabled: "Trailing", htf_filter: "Filtro TF superior", symbol_params: "Parámetros SL/TP",
};
const fmtVal = (k, v) => {
  if (v == null) return "—";
  if (typeof v === "boolean") return v ? "Sí" : "No";
  if (k === "strategy") return STRATEGY_LABELS[v] || v;
  if (Array.isArray(v)) return v.map((s) => s.replace("USDT", "")).join(", ") || "ninguno";
  if (typeof v === "object") return Object.entries(v).map(([s, p]) => `${s.replace("USDT", "")}: SL ${p.sl_atr}× TP ${p.tp_atr}× ATR ${p.atr_period}`).join(" · ") || "ninguno";
  return String(v);
};

export default function AiAdvice({ scope, payload = {}, onDone, label = "Analizar y ajustar con IA", testId = "ai-advice" }) {
  const [res, setRes] = useState(null);
  const [loading, setLoading] = useState(false);
  const [undone, setUndone] = useState(false);

  const run = async () => {
    setLoading(true);
    setUndone(false);
    try {
      const { data } = await http.post("/ai/advise", { scope, ...payload });
      setRes(data);
      const n = Object.keys(data.applied).length;
      toast.success(n ? `Claude aplicó ${n} cambio${n > 1 ? "s" : ""} a la configuración` : "Claude revisó el análisis · sin cambios necesarios");
      onDone?.();
    } catch (e) {
      toast.error(errMsg(e));
    } finally {
      setLoading(false);
    }
  };

  const undo = async () => {
    try {
      await http.put("/settings", res.previous);
      setUndone(true);
      toast.success("Cambios de la IA revertidos");
      onDone?.();
    } catch (e) {
      toast.error(errMsg(e));
    }
  };

  const applied = res ? Object.entries(res.applied) : [];
  return (
    <div data-testid={testId} className="space-y-3">
      <Button data-testid={`${testId}-button`} onClick={run} disabled={loading}
        className="h-9 border border-purple-500/40 bg-purple-500/10 font-mono text-[11px] font-bold uppercase tracking-wider text-purple-200 hover:bg-purple-500/20">
        {loading ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Sparkles className="mr-1.5 h-3.5 w-3.5" />}
        {loading ? "Claude analizando..." : label}
      </Button>
      {res && (
        <div data-testid={`${testId}-result`} className="rounded-md border border-purple-500/30 bg-purple-500/5 p-4">
          <div className="flex items-start gap-2">
            <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-purple-300" />
            <p data-testid={`${testId}-summary`} className="text-[12.5px] leading-relaxed text-slate-200">{res.summary}</p>
          </div>
          <div className="mt-3 space-y-1.5">
            <p className="font-mono text-[10px] uppercase tracking-wider text-slate-500">{applied.length ? `Cambios aplicados (${applied.length})` : "Sin cambios de configuración"}</p>
            {applied.map(([k, v]) => (
              <div key={k} data-testid={`${testId}-change-${k}`} className="flex flex-wrap items-baseline gap-x-2 font-mono text-[11px]">
                <CheckCircle2 className="h-3 w-3 text-emerald-400" />
                <span className="text-slate-300">{LABELS[k] || k}:</span>
                <span className="text-slate-500 line-through">{fmtVal(k, v.antes)}</span>
                <span className="text-emerald-300">→ {fmtVal(k, v.despues)}</span>
              </div>
            ))}
          </div>
          {res.notes?.length > 0 && (
            <ul className="mt-3 space-y-1">
              {res.notes.map((n, i) => (
                <li key={i} className="flex gap-2 text-[11.5px] leading-snug text-slate-400"><Info className="mt-0.5 h-3 w-3 shrink-0 text-slate-500" />{n}</li>
              ))}
            </ul>
          )}
          {applied.length > 0 && !undone && (
            <Button data-testid={`${testId}-undo-button`} onClick={undo} variant="outline" size="sm" className="mt-3 h-7 border-[#1E293B] bg-transparent font-mono text-[10px] uppercase tracking-wider text-slate-300 hover:bg-[#111827]">
              <Undo2 className="mr-1 h-3 w-3" /> Deshacer cambios
            </Button>
          )}
          {undone && <p className="mt-3 font-mono text-[10px] uppercase tracking-wider text-slate-500">Cambios revertidos</p>}
        </div>
      )}
    </div>
  );
}
