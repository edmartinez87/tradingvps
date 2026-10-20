import { TH, TD } from "../PositionsTable";
import { VerdictBadge } from "./WalkForward";

export default function OptimizerSummary({ list, onSelect }) {
  return (
    <div data-testid="optimizer-summary" className="overflow-x-auto thin-scroll rounded-sm border border-[#1E293B]">
      <table className="w-full text-sm">
        <thead className="border-b border-[#1E293B] bg-[#0D111A]">
          <tr><TH>Par</TH><TH>Óptimo robusto</TH><TH right>PF base → óptimo</TH><TH right>Retorno base → óptimo</TH><TH right>Robustez</TH><TH right>Ops</TH><TH>Walk-forward</TH><TH>Estado</TH></tr>
        </thead>
        <tbody className="num text-[12px]">
          {list.map((r) => (
            <tr key={r.symbol} data-testid={`optimizer-summary-${r.symbol}`} onClick={() => onSelect(r.symbol)} className="cursor-pointer border-b border-[#1E293B]/60 transition-colors hover:bg-[#111827]">
              <TD className="font-display text-[13px] font-semibold text-slate-100">{r.symbol}</TD>
              <TD className="text-slate-300">{r.best ? `SL ${r.best.sl_atr}× · TP ${r.best.tp_atr}× · ATR ${r.best.atr_period}` : "—"}</TD>
              <TD right><span className="text-slate-500">{r.baseline.profit_factor}</span> → <span className={r.best && r.best.profit_factor >= r.baseline.profit_factor ? "text-emerald-400" : "text-rose-400"}>{r.best?.profit_factor ?? "—"}</span></TD>
              <TD right><span className="text-slate-500">{r.baseline.return_pct}%</span> → <span className={r.best && r.best.return_pct >= r.baseline.return_pct ? "text-emerald-400" : "text-rose-400"}>{r.best ? `${r.best.return_pct}%` : "—"}</span></TD>
              <TD right className="text-amber-400">{r.best?.robust ?? "—"}</TD>
              <TD right>{r.best?.trades ?? "—"}</TD>
              <TD>{r.wf_verdict ? <VerdictBadge verdict={r.wf_verdict} testId={`optimizer-summary-wf-${r.symbol}`} /> : <span className="font-mono text-[10px] text-slate-600">—</span>}</TD>
              <TD>{r.applied ? <span className="rounded-sm border border-emerald-500/30 px-1.5 py-0.5 font-mono text-[10px] uppercase text-emerald-400">Aplicado</span> : <span className="font-mono text-[10px] uppercase text-slate-500">Por defecto</span>}</TD>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
