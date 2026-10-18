import { Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";

const ROWS = [
  ["Retorno", "return_pct", (v) => `${v > 0 ? "+" : ""}${v}%`, true],
  ["Profit factor", "profit_factor", (v) => v, true],
  ["SQN", "sqn", (v) => v, true],
  ["Expectativa (R)", "expectancy_r", (v) => `${v > 0 ? "+" : ""}${v}`, true],
  ["Operaciones", "trades", (v) => v, false],
  ["Acierto", "win_rate", (v) => `${v}%`, true],
  ["Máx. drawdown", "max_drawdown", (v) => `${v}%`, false],
];

const Params = ({ p, label, cls }) => (
  <div>
    <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-slate-500">{label}</p>
    <p data-testid={`optimizer-${label === "Línea base" ? "baseline" : "best"}-params`} className={`num mt-1 text-sm font-semibold ${cls}`}>
      {p ? `SL ${p.sl_atr}×ATR · TP ${p.tp_atr}×ATR · ATR ${p.atr_period}` : "Valores por defecto de cada estrategia"}
    </p>
  </div>
);

export default function OptimizerCompare({ res, onApply, onRemove }) {
  const { best, baseline, applied } = res;
  if (!best) return <p data-testid="optimizer-no-best" className="text-[12px] text-slate-500">Ninguna combinación alcanzó el mínimo de operaciones para considerarse fiable.</p>;
  const isApplied = applied && applied.sl_atr === best.sl_atr && applied.tp_atr === best.tp_atr && applied.atr_period === best.atr_period;
  const better = best.sqn > baseline.sqn && best.profit_factor >= baseline.profit_factor;
  return (
    <div data-testid="optimizer-compare" className="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_auto]">
      <div className="overflow-hidden rounded-md border border-[#1E293B]">
        <div className="grid grid-cols-[1fr_1fr_1fr] gap-px bg-[#1E293B]">
          <div className="bg-[#0D111A] px-3 py-2.5 font-mono text-[9px] uppercase tracking-[0.16em] text-slate-500">Métrica</div>
          <div className="bg-[#0D111A] px-3 py-2.5"><Params p={null} label="Línea base" cls="text-slate-300" /></div>
          <div className="bg-[#0D111A] px-3 py-2.5"><Params p={best} label="Óptimo robusto" cls="text-amber-400" /></div>
          {ROWS.map(([label, k, f, higherBetter]) => {
            const win = k === "max_drawdown" ? best[k] < baseline[k] : higherBetter && best[k] > baseline[k];
            return [
              <div key={`${k}-l`} className="bg-[#0D111A] px-3 py-2 text-[11px] text-slate-400">{label}</div>,
              <div key={`${k}-b`} className="num bg-[#0D111A] px-3 py-2 text-[12px] text-slate-300">{f(baseline[k])}</div>,
              <div key={`${k}-o`} data-testid={`optimizer-best-${k}`} className={`num bg-[#0D111A] px-3 py-2 text-[12px] font-semibold ${win ? "text-emerald-400" : "text-slate-200"}`}>{f(best[k])}</div>,
            ];
          })}
        </div>
      </div>
      <div className="flex flex-col justify-between gap-3 rounded-md border border-[#1E293B] bg-[#0D111A] p-3 lg:w-[240px]">
        <div>
          <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-slate-500">Puntuación robusta</p>
          <p data-testid="optimizer-robust-score" className="num mt-1 text-2xl font-semibold text-amber-400">{best.robust}</p>
          <p className="mt-1 text-[11px] leading-snug text-slate-500">SQN medio de {best.neighbors} combinaciones vecinas. {best.expectancy_r <= 0 ? "Ninguna combinación es rentable en este par con estos datos: considera desactivarlo." : better ? "Supera a la línea base en calidad y profit factor." : "No supera con claridad a la línea base: aplícalo con cautela."}</p>
        </div>
        {isApplied ? (
          <div className="space-y-2">
            <p data-testid="optimizer-applied-badge" className="inline-flex items-center gap-1 rounded-sm border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-emerald-400"><Check className="h-3 w-3" /> Aplicado al bot</p>
            <Button data-testid="optimizer-remove-button" onClick={onRemove} variant="outline" size="sm" className="h-7 w-full border-[#1E293B] bg-transparent font-mono text-[10px] uppercase tracking-wider text-slate-300 hover:bg-[#111827]"><X className="mr-1 h-3 w-3" /> Volver a valores por defecto</Button>
          </div>
        ) : (
          <Button data-testid="optimizer-apply-button" onClick={onApply} className="h-9 w-full bg-amber-500 font-mono text-[11px] font-bold uppercase tracking-wider text-[#07090E] hover:bg-amber-400">Aplicar al bot</Button>
        )}
      </div>
    </div>
  );
}
