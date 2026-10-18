import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { Empty } from "./Panel";
import { TH, TD } from "./PositionsTable";
import { http, fmtSignedUsd, pnlClass, STRATEGY_LABELS, REASON_LABELS } from "@/lib/api";

const SIDE = { long: "Long", short: "Short" };
const DECISION = { APROBADA: "Aprobadas IA", RECHAZADA: "Rechazadas IA", BLOQUEADA: "Bloqueadas riesgo", SIN_IA: "Sin IA", ERROR: "Error IA" };

const Group = ({ title, label, rows, render = (k) => k, testId }) => (
  <div data-testid={testId} className="overflow-hidden rounded-sm border border-[#1E293B]">
    <p className="border-b border-[#1E293B] bg-[#0D111A] px-3 py-2 font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">{title}</p>
    <table className="w-full text-sm">
      <thead><tr><TH>{label}</TH><TH right>Ops</TH><TH right>Acierto</TH><TH right>PF</TH><TH right>PnL medio</TH><TH right>PnL</TH></tr></thead>
      <tbody className="num text-[12px]">
        {rows.map((r) => (
          <tr key={r.key} data-testid={`perf-row-${r.key}`} className="border-t border-[#1E293B]/60 transition-colors hover:bg-[#111827]">
            <TD className="font-display text-[13px] font-semibold text-slate-100">{render(r.key)}</TD>
            <TD right>{r.trades}</TD>
            <TD right>{r.win_rate}%</TD>
            <TD right className={r.profit_factor == null ? "text-slate-500" : r.profit_factor >= 1 ? "text-emerald-400" : "text-rose-400"}>{r.profit_factor ?? "∞"}</TD>
            <TD right className={pnlClass(r.avg_pnl)}>{fmtSignedUsd(r.avg_pnl)}</TD>
            <TD right className={`font-semibold ${pnlClass(r.pnl)}`}>{fmtSignedUsd(r.pnl)}</TD>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

export default function Performance({ tradeCount }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    http.get("/performance").then((r) => setData(r.data)).catch(() => {});
  }, [tradeCount]);

  if (!data) return <div className="flex min-h-[120px] items-center justify-center text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /></div>;
  const sig = data.signals;
  return (
    <div data-testid="performance-panel" className="space-y-4 p-4">
      <p className="text-[12px] leading-relaxed text-slate-400">
        Rendimiento real del paper trading por estrategia y par. Úsalo para desactivar lo que pierde y concentrar el capital en lo que funciona (mínimo 30 operaciones por fila antes de decidir).
      </p>
      <div data-testid="perf-signals" className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-[#1E293B] bg-[#1E293B] sm:grid-cols-4 lg:grid-cols-6">
        {[["Señales", sig.total], ["Ejecutadas", sig.executed], ...Object.entries(sig.by_decision).map(([k, v]) => [DECISION[k] || k, v])].map(([l, v]) => (
          <div key={l} className="bg-[#0D111A] px-3 py-2.5">
            <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-slate-500">{l}</p>
            <p className="num mt-1 text-base font-semibold text-slate-100">{v}</p>
          </div>
        ))}
      </div>
      {!data.by_strategy.length ? (
        <Empty testId="performance-empty" text="Aún no hay operaciones cerradas. Las estadísticas aparecerán con las primeras operaciones del bot." />
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <Group title="Por estrategia" label="Estrategia" rows={data.by_strategy} render={(k) => STRATEGY_LABELS[k] || k} testId="perf-by-strategy" />
          <Group title="Por par" label="Par" rows={data.by_symbol} testId="perf-by-symbol" />
          <Group title="Por dirección" label="Lado" rows={data.by_side} render={(k) => SIDE[k] || k} testId="perf-by-side" />
          <Group title="Por tipo de salida" label="Salida" rows={data.by_reason} render={(k) => REASON_LABELS[k] || k} testId="perf-by-reason" />
        </div>
      )}
    </div>
  );
}
