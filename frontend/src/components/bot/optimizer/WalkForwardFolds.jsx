import { TH, TD } from "../PositionsTable";
import { fmtDateTime } from "@/lib/api";

const sign = (v, d = 2) => (v == null ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(d)}`);
const cls = (v) => (v > 0 ? "text-emerald-400" : v < 0 ? "text-rose-400" : "text-slate-300");

export default function WalkForwardFolds({ folds }) {
  if (!folds.length) return null;
  return (
    <div data-testid="wf-folds" className="overflow-x-auto thin-scroll rounded-sm border border-[#1E293B]">
      <table className="w-full text-sm">
        <thead className="border-b border-[#1E293B] bg-[#0D111A]">
          <tr>
            <TH>Tramo</TH><TH>Fuera de muestra</TH><TH>Óptimo in-sample</TH>
            <TH right>Exp. IS (R)</TH><TH right>Ops IS</TH><TH right>Exp. OOS (R)</TH><TH right>Ops OOS</TH><TH right>Retorno OOS</TH><TH right>Base OOS</TH>
          </tr>
        </thead>
        <tbody className="num text-[12px]">
          {folds.map((f) => (
            <tr key={f.fold} data-testid={`wf-fold-${f.fold}`} className="border-b border-[#1E293B]/60">
              <TD className="font-display text-[13px] font-semibold text-slate-100">#{f.fold}</TD>
              <TD className="text-slate-400">{fmtDateTime(f.split)} → {fmtDateTime(f.oos_end)}</TD>
              <TD className="text-slate-300">{f.params ? `SL ${f.params.sl_atr}× · TP ${f.params.tp_atr}× · ATR ${f.params.atr_period}` : <span className="text-slate-500">sin óptimo (usa defecto)</span>}<span className="ml-1 text-[10px] text-slate-500">· {f.is_candles} velas</span></TD>
              <TD right className={cls(f.is?.expectancy_r)}>{sign(f.is?.expectancy_r, 3)}</TD>
              <TD right>{f.is?.trades ?? "—"}</TD>
              <TD right className={`font-semibold ${cls(f.oos.expectancy_r)}`}>{sign(f.oos.expectancy_r, 3)}</TD>
              <TD right>{f.oos.trades}</TD>
              <TD right className={cls(f.oos.return_pct)}>{sign(f.oos.return_pct)}%</TD>
              <TD right className={cls(f.baseline_oos.return_pct)}>{sign(f.baseline_oos.return_pct)}%</TD>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
