import { useEffect, useRef, useState } from "react";
import { Loader2, Target, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { http, errMsg, fmtDateTime } from "@/lib/api";
import { AiResult } from "./AiAdvice";
import OptimizerCompare from "./optimizer/OptimizerCompare";
import OptimizerHeatmap from "./optimizer/OptimizerHeatmap";
import OptimizerSummary from "./optimizer/OptimizerSummary";

export default function Optimizer({ settings, onSave, refresh }) {
  const [symbol, setSymbol] = useState(settings.symbols[0]);
  const [results, setResults] = useState({});
  const [loading, setLoading] = useState(null);
  const [job, setJob] = useState(null);
  const timer = useRef(null);

  const runOne = async (sym) => {
    const { data } = await http.post("/optimize", { symbol: sym });
    setResults((r) => ({ ...r, [sym]: data }));
    return data;
  };
  const run = async (all = false) => {
    const syms = all ? settings.symbols : [symbol];
    for (const s of syms) {
      setLoading(s);
      try { await runOne(s); } catch (e) { toast.error(`${s}: ${errMsg(e)}`); }
    }
    setLoading(null);
    if (all) toast.success(`Optimización completada para ${syms.length} pares`);
  };

  const absorb = (j) => {
    setJob(j);
    if (j.status === "done" && j.result) {
      setResults(Object.fromEntries((j.result.optimizer || []).map((r) => [r.symbol, r])));
      const n = Object.keys(j.result.applied || {}).length;
      toast.success(n ? `Claude aplicó ${n} cambio${n > 1 ? "s" : ""} a la configuración` : "Claude revisó todo · sin cambios necesarios");
      refresh?.();
    } else if (j.status === "error") {
      toast.error(j.error || "La optimización global falló");
    }
  };
  const poll = async () => {
    try {
      const { data } = await http.get("/ai/optimize-all");
      if (data.status === "running") { setJob(data); timer.current = setTimeout(poll, 2500); } else absorb(data);
    } catch (e) {
      toast.error(errMsg(e));
      setJob(null);
    }
  };
  useEffect(() => {
    http.get("/ai/optimize-all").then(({ data }) => { if (data.status === "running") { setJob(data); timer.current = setTimeout(poll, 2500); } else if (data.status === "done") setJob(data); }).catch(() => {});
    return () => clearTimeout(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const optimizeAll = async () => {
    try {
      const { data } = await http.post("/ai/optimize-all");
      setJob(data);
      timer.current = setTimeout(poll, 2500);
    } catch (e) {
      toast.error(errMsg(e));
    }
  };

  const apply = async (sym, best) => {
    const params = { sl_atr: best.sl_atr, tp_atr: best.tp_atr, atr_period: best.atr_period };
    await onSave({ symbol_params: { ...settings.symbol_params, [sym]: params } });
  };
  const remove = async (sym) => {
    const next = { ...settings.symbol_params };
    delete next[sym];
    await onSave({ symbol_params: next });
  };

  const withApplied = (r) => ({ ...r, applied: settings.symbol_params[r.symbol] || null });
  const res = results[symbol] ? withApplied(results[symbol]) : null;
  const list = Object.values(results).map(withApplied);
  const running = job?.status === "running";
  return (
    <div data-testid="optimizer-panel" className="space-y-4 p-4">
      <div data-testid="optimize-all-card" className="rounded-md border border-purple-500/30 bg-purple-500/[0.06] p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-[240px] flex-1">
            <p className="flex items-center gap-1.5 font-display text-[15px] font-bold text-purple-200"><Sparkles className="h-4 w-4" /> Optimizar todo con IA</p>
            <p className="mt-1 text-[12px] leading-relaxed text-slate-400">
              Corre el optimizador en los {settings.symbols.length} pares activos y Claude cruza esos resultados con las operaciones reales por par y estrategia, el backtest y el plan.
              Apaga lo que pierde, aplica los SL/TP óptimos y ajusta los filtros, siempre dentro de los topes de tu perfil de riesgo. Los cambios se aplican directamente y te avisa por Telegram.
            </p>
          </div>
          <Button data-testid="optimize-all-button" onClick={optimizeAll} disabled={running || !!loading}
            className="h-10 bg-purple-500 font-mono text-[11px] font-bold uppercase tracking-wider text-white hover:bg-purple-400 disabled:opacity-50">
            {running ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Sparkles className="mr-1.5 h-4 w-4" />}
            {running ? (job.step || "Trabajando...") : "Optimizar todo con IA"}
          </Button>
        </div>
        {job?.status === "done" && job.result && (
          <div className="mt-3">
            <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-slate-500">Última optimización global · {fmtDateTime(job.result.ran_at)}</p>
            <AiResult key={job.result.ran_at} res={job.result} testId="optimize-all" onDone={refresh} />
          </div>
        )}
        {job?.status === "error" && <p data-testid="optimize-all-error" className="mt-3 font-mono text-[11px] text-rose-300">Error: {job.error}</p>}
      </div>

      <p className="text-[12px] leading-relaxed text-slate-400">
        Optimización manual por par: prueba 54 combinaciones de stop (1.0–3.0×ATR), objetivo (2.0–6.0×ATR, R:R ≥ 1.5) y periodo ATR (10/14/20) sobre las últimas 1.000 velas {settings.timeframe}.
        Elige la combinación más <span className="text-slate-200">robusta</span>: SQN de Van Tharp promediado con sus vecinas, para evitar el sobreajuste.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[150px]">
          <p className="mb-1 font-mono text-[10px] uppercase tracking-wider text-slate-500">Par</p>
          <Select value={symbol} onValueChange={setSymbol}>
            <SelectTrigger data-testid="optimizer-symbol-select" className="h-9 border-[#1E293B] bg-[#07090E] font-mono text-xs"><SelectValue /></SelectTrigger>
            <SelectContent className="border-[#1E293B] bg-[#0D111A]">
              {settings.symbols.map((s) => <SelectItem key={s} value={s} className="font-mono text-xs">{s}{settings.symbol_params[s] ? " ·" : ""}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <Button data-testid="optimizer-run-button" onClick={() => run(false)} disabled={!!loading || running} className="h-9 bg-amber-500 font-mono text-[11px] font-bold uppercase tracking-wider text-[#07090E] hover:bg-amber-400">
          {loading === symbol ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Target className="mr-1.5 h-3.5 w-3.5" />} Optimizar par
        </Button>
        <Button data-testid="optimizer-run-all-button" onClick={() => run(true)} disabled={!!loading || running} variant="outline" className="h-9 border-[#1E293B] bg-transparent font-mono text-[11px] uppercase tracking-wider text-slate-200 hover:bg-[#111827]">
          {loading ? <><Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> {loading}</> : `Optimizar todos (${settings.symbols.length})`}
        </Button>
      </div>

      {res && (
        <div data-testid="optimizer-results" className="space-y-4">
          <p className="font-mono text-[10px] uppercase tracking-wider text-slate-500">
            {res.symbol} · {res.timeframe} · {res.combos} combinaciones · {fmtDateTime(res.period_start)} → {fmtDateTime(res.period_end)}
          </p>
          <OptimizerCompare res={res} onApply={() => apply(res.symbol, res.best)} onRemove={() => remove(res.symbol)} />
          <OptimizerHeatmap key={res.symbol} res={res} />
        </div>
      )}
      {list.length > 1 && <OptimizerSummary list={list} onSelect={setSymbol} />}
    </div>
  );
}
