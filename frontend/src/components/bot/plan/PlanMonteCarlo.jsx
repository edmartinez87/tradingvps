import { TH, TD } from "../PositionsTable";
import { STRATEGY_LABELS, fmtPct, fmtSignedUsd } from "@/lib/api";

const Metric = ({ label, value, cls = "text-slate-100", testId }) => (
  <div className="bg-[#0D111A] px-3 py-2.5">
    <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-slate-500">{label}</p>
    <p data-testid={testId} className={`num mt-1 text-sm font-semibold ${cls}`}>{value}</p>
  </div>
);
const tone = (v) => (v > 0 ? "text-emerald-400" : v < 0 ? "text-rose-400" : "text-slate-100");
const pf = (v) => (v == null ? "∞" : v);

const Table = ({ title, rows, keyField, render = (k) => k, testId }) => (
  <div data-testid={testId} className="overflow-hidden rounded-sm border border-[#1E293B]">
    <p className="border-b border-[#1E293B] bg-[#0D111A] px-3 py-2 font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">{title}</p>
    <table className="w-full text-sm">
      <thead><tr><TH>{keyField === "symbol" ? "Par" : "Estrategia"}</TH><TH right>Ops</TH><TH right>Acierto</TH><TH right>PF</TH><TH right>Expect. (R)</TH><TH right>{keyField === "symbol" ? "Retorno" : "PnL"}</TH></tr></thead>
      <tbody className="num text-[12px]">
        {rows.map((r) => (
          <tr key={r[keyField]} data-testid={`plan-bt-${r[keyField]}`} className="border-t border-[#1E293B]/60">
            <TD className="font-display text-[13px] font-semibold text-slate-100">{render(r[keyField])}{r.rejected_lot > 0 && <span className="ml-1 text-[9px] text-amber-400" title="Órdenes rechazadas por lote mínimo">lote×{r.rejected_lot}</span>}</TD>
            <TD right>{r.trades}</TD>
            <TD right>{r.win_rate}%</TD>
            <TD right className={r.profit_factor == null || r.profit_factor >= 1 ? "text-emerald-400" : "text-rose-400"}>{pf(r.profit_factor)}</TD>
            <TD right className={tone(r.expectancy_r)}>{r.expectancy_r > 0 ? "+" : ""}{r.expectancy_r}</TD>
            <TD right className={`font-semibold ${tone(keyField === "symbol" ? r.return_pct : r.pnl)}`}>{keyField === "symbol" ? fmtPct(r.return_pct) : fmtSignedUsd(r.pnl)}</TD>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

export default function PlanMonteCarlo({ backtest: bt }) {
  const mc = bt.monte_carlo;
  return (
    <div data-testid="plan-montecarlo" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="font-display text-[12px] font-semibold uppercase tracking-[0.14em] text-slate-200">Monte Carlo · {mc ? mc.sims.toLocaleString("es-ES") : 0} simulaciones de 12 meses</h4>
        <p className="font-mono text-[10px] uppercase tracking-wider text-slate-500">
          backtest {bt.days} días · {bt.timeframe} · {bt.total_trades} ops · {bt.trades_per_month} ops/mes estimadas (factor concurrencia {bt.concurrency_factor})
        </p>
      </div>
      {mc ? (
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-[#1E293B] bg-[#1E293B] sm:grid-cols-4 xl:grid-cols-8">
          <Metric label="Mes mediano" value={fmtPct(mc.monthly_median)} cls={tone(mc.monthly_median)} testId="mc-monthly-median" />
          <Metric label="Mes malo (P10)" value={fmtPct(mc.monthly_p10)} cls={tone(mc.monthly_p10)} testId="mc-monthly-p10" />
          <Metric label="Mes bueno (P90)" value={fmtPct(mc.monthly_p90)} cls={tone(mc.monthly_p90)} testId="mc-monthly-p90" />
          <Metric label="Meses positivos" value={`${mc.prob_positive_month}%`} testId="mc-prob-positive" />
          <Metric label="Año mediano" value={fmtPct(mc.annual_median)} cls={tone(mc.annual_median)} testId="mc-annual-median" />
          <Metric label="Prob. año en pérdida" value={`${mc.prob_loss_year}%`} cls={mc.prob_loss_year > 30 ? "text-rose-400" : "text-slate-100"} testId="mc-prob-loss-year" />
          <Metric label="Drawdown típico" value={`${mc.median_max_dd}%`} testId="mc-median-dd" />
          <Metric label="Prob. DD > 15%" value={`${mc.prob_dd_over_15}%`} cls={mc.prob_dd_over_15 > 30 ? "text-rose-400" : "text-slate-100"} testId="mc-prob-dd15" />
        </div>
      ) : (
        <p className="text-[12px] text-slate-500">Datos insuficientes para Monte Carlo (menos de 10 operaciones en el backtest).</p>
      )}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Table title="Backtest por par · últimos datos reales" rows={bt.per_symbol} keyField="symbol" testId="plan-bt-symbols" />
        <Table title="Backtest por estrategia" rows={bt.by_strategy} keyField="strategy" render={(k) => STRATEGY_LABELS[k] || k} testId="plan-bt-strategies" />
      </div>
    </div>
  );
}
