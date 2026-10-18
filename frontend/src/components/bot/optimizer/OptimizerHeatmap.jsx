import { useState } from "react";

const color = (v, min, max) => {
  if (v == null) return "transparent";
  const t = max > min ? (v - min) / (max - min) : 0.5;
  return v >= 0 ? `rgba(16,185,129,${0.12 + 0.55 * t})` : `rgba(239,68,68,${0.15 + 0.5 * (1 - t)})`;
};

export default function OptimizerHeatmap({ res }) {
  const [atr, setAtr] = useState(res.best?.atr_period ?? res.atr_grid[1]);
  const cells = res.grid.filter((r) => r.atr_period === atr);
  const vals = cells.map((c) => c.robust);
  const min = Math.min(...vals), max = Math.max(...vals);
  const at = (sl, tp) => cells.find((c) => c.sl_atr === sl && c.tp_atr === tp);
  return (
    <div data-testid="optimizer-heatmap" className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-mono text-[10px] uppercase tracking-wider text-slate-500">Mapa de robustez · filas SL×ATR · columnas TP×ATR · celda: puntuación robusta / operaciones</p>
        <div className="flex gap-1">
          {res.atr_grid.map((a) => (
            <button key={a} data-testid={`optimizer-atr-${a}`} onClick={() => setAtr(a)}
              className={`rounded-sm border px-2 py-1 font-mono text-[10px] transition-colors ${a === atr ? "border-amber-500/60 bg-amber-500/15 text-amber-300" : "border-[#1E293B] text-slate-500 hover:text-slate-200"}`}>
              ATR {a}{res.best?.atr_period === a ? " ★" : ""}
            </button>
          ))}
        </div>
      </div>
      <div className="overflow-x-auto thin-scroll">
        <table className="w-full min-w-[520px] border-separate border-spacing-1 text-center">
          <thead>
            <tr><th className="font-mono text-[10px] text-slate-500">SL \ TP</th>{res.tp_grid.map((tp) => <th key={tp} className="font-mono text-[10px] text-slate-400">{tp}×</th>)}</tr>
          </thead>
          <tbody>
            {res.sl_grid.map((sl) => (
              <tr key={sl}>
                <td className="font-mono text-[10px] text-slate-400">{sl}×</td>
                {res.tp_grid.map((tp) => {
                  const c = at(sl, tp);
                  const best = res.best && c && c.sl_atr === res.best.sl_atr && c.tp_atr === res.best.tp_atr && atr === res.best.atr_period;
                  return (
                    <td key={tp} data-testid={`optimizer-cell-${sl}-${tp}`} title={c ? `Retorno ${c.return_pct}% · PF ${c.profit_factor} · DD ${c.max_drawdown}% · SQN ${c.sqn}` : "R:R < 1.5 (descartado)"}
                      className={`rounded-sm px-1 py-1.5 font-mono text-[10px] ${best ? "ring-2 ring-amber-400" : ""} ${c ? "text-slate-100" : "text-slate-700"}`}
                      style={{ background: color(c?.robust, min, max) }}>
                      {c ? <><span className="block font-semibold">{c.robust}</span><span className="text-[9px] text-slate-300/80">{c.trades} ops</span></> : "—"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
