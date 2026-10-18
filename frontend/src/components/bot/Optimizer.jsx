import { useState } from "react";
import { Loader2, Target } from "lucide-react";
import { toast } from "sonner";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { http, errMsg, fmtDateTime } from "@/lib/api";
import AiAdvice from "./AiAdvice";
import OptimizerCompare from "./optimizer/OptimizerCompare";
import OptimizerHeatmap from "./optimizer/OptimizerHeatmap";
import OptimizerSummary from "./optimizer/OptimizerSummary";

export default function Optimizer({ settings, onSave, refresh }) {
  const [symbol, setSymbol] = useState(settings.symbols[0]);
  const [results, setResults] = useState({});
  const [loading, setLoading] = useState(null);

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
  return (
    <div data-testid="optimizer-panel" className="space-y-4 p-4">
      <p className="text-[12px] leading-relaxed text-slate-400">
        Prueba 54 combinaciones de stop (1.0–3.0×ATR), objetivo (2.0–6.0×ATR, R:R ≥ 1.5) y periodo ATR (10/14/20) sobre las últimas 1.000 velas {settings.timeframe} del par.
        Elige la combinación más <span className="text-slate-200">robusta</span>: SQN de Van Tharp (expectativa ÷ desviación × √operaciones) promediado con sus vecinas, para evitar el sobreajuste.
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
        <Button data-testid="optimizer-run-button" onClick={() => run(false)} disabled={!!loading} className="h-9 bg-amber-500 font-mono text-[11px] font-bold uppercase tracking-wider text-[#07090E] hover:bg-amber-400">
          {loading === symbol ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Target className="mr-1.5 h-3.5 w-3.5" />} Optimizar par
        </Button>
        <Button data-testid="optimizer-run-all-button" onClick={() => run(true)} disabled={!!loading} variant="outline" className="h-9 border-[#1E293B] bg-transparent font-mono text-[11px] uppercase tracking-wider text-slate-200 hover:bg-[#111827]">
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
      {list.length > 0 && (
        <AiAdvice scope="optimizer" testId="optimizer-ai" label="Ajustar el bot con IA según este análisis"
          payload={{ optimizer_results: list.map((r) => ({ symbol: r.symbol, best: r.best, baseline: r.baseline, timeframe: r.timeframe })) }}
          onDone={refresh} />
      )}
    </div>
  );
}
