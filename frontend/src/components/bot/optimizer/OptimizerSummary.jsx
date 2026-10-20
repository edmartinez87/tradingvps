import { Loader2, FlaskConical } from "lucide-react";
import { TH, TD } from "../PositionsTable";
import { VerdictBadge } from "./WalkForward";

const BAD = ["SOBREAJUSTADO", "NO_RENTABLE"];
const LIGHT = {
  green: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  amber: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  red: "border-rose-500/40 bg-rose-500/10 text-rose-300",
  grey: "border-slate-600/50 bg-slate-500/10 text-slate-400",
};

export function decide(r, verdict, appliedVerdict) {
  if (r.applied) {
    const av = appliedVerdict || verdict;
    if (!av) return { color: "grey", text: "Falta walk-forward" };
    if (BAD.includes(av)) return { color: "red", text: "Quitar parámetros" };
    if (av === "INSUFICIENTE") return { color: "grey", text: "Sin datos OOS" };
    if (av === "ROBUSTO") return { color: "green", text: "Mantener" };
    return { color: "amber", text: "Vigilar" };
  }
  if (!r.best) return { color: "grey", text: "Sin óptimo fiable" };
  const better = r.best.sqn > r.baseline.sqn && r.best.profit_factor >= r.baseline.profit_factor;
  if (r.best.expectancy_r <= 0 || BAD.includes(verdict)) return { color: "red", text: "No aplicar" };
  if (!verdict) return { color: "grey", text: "Falta walk-forward" };
  if (verdict === "INSUFICIENTE") return { color: "grey", text: "Sin datos OOS" };
  if (verdict === "ROBUSTO" && better) return { color: "green", text: "Aplicar" };
  if (verdict === "DUDOSO" && !better) return { color: "red", text: "No aplicar" };
  return { color: "amber", text: "Con cautela" };
}

const Light = ({ d, testId }) => (
  <span data-testid={testId} className={`inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider ${LIGHT[d.color]}`}>
    <span className={`h-1.5 w-1.5 rounded-full ${d.color === "green" ? "bg-emerald-400" : d.color === "amber" ? "bg-amber-400" : d.color === "red" ? "bg-rose-400" : "bg-slate-500"}`} /> {d.text}
  </span>
);

export default function OptimizerSummary({ list, onSelect, onValidate, validating }) {
  return (
    <div data-testid="optimizer-summary" className="overflow-x-auto thin-scroll rounded-sm border border-[#1E293B]">
      <table className="w-full text-sm">
        <thead className="border-b border-[#1E293B] bg-[#0D111A]">
          <tr><TH>Par</TH><TH>Óptimo robusto</TH><TH right>PF base → óptimo</TH><TH right>Retorno base → óptimo</TH><TH right>Robustez</TH><TH right>Ops</TH><TH>Walk-forward</TH><TH>Decisión</TH><TH>Estado</TH></tr>
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
              <TD>
                {r.wf_verdict ? (
                  <span className="inline-flex flex-wrap items-center gap-1">
                    <VerdictBadge verdict={r.wf_verdict} testId={`optimizer-summary-wf-${r.symbol}`} />
                    {r.applied && r.applied_verdict && <span data-testid={`optimizer-summary-applied-wf-${r.symbol}`} className="font-mono text-[9px] uppercase text-amber-300/80" title="Veredicto de los SL/TP aplicados">aplicados: {r.applied_verdict}</span>}
                  </span>
                ) : (
                  <button data-testid={`optimizer-summary-validate-${r.symbol}`} onClick={(e) => { e.stopPropagation(); onValidate(r.symbol); }} disabled={!!validating}
                    className="inline-flex items-center gap-1 rounded-sm border border-sky-500/30 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-sky-300 transition-colors hover:bg-sky-500/10 disabled:opacity-50">
                    {validating === r.symbol ? <Loader2 className="h-3 w-3 animate-spin" /> : <FlaskConical className="h-3 w-3" />} Validar
                  </button>
                )}
              </TD>
              <TD><Light d={decide(r, r.wf_verdict, r.applied_verdict)} testId={`optimizer-summary-decision-${r.symbol}`} /></TD>
              <TD>{r.applied ? <span className="rounded-sm border border-emerald-500/30 px-1.5 py-0.5 font-mono text-[10px] uppercase text-emerald-400">Aplicado</span> : <span className="font-mono text-[10px] uppercase text-slate-500">Por defecto</span>}</TD>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
