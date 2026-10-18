import { fmtUsd, fmtSignedUsd, fmtPct, pnlClass } from "@/lib/api";

export default function KpiStrip({ account: a }) {
  const items = [
    { k: "balance", label: "Balance", value: fmtUsd(a.balance), sub: `Disponible ${fmtUsd(a.available)}` },
    { k: "equity", label: "Equidad", value: fmtUsd(a.equity), sub: `Retorno ${fmtPct(a.total_return_pct)}`, subTone: a.total_return_pct },
    { k: "unrealized", label: "PnL no realizado", value: fmtSignedUsd(a.unrealized_pnl), tone: a.unrealized_pnl, sub: fmtPct(a.unrealized_pct), subTone: a.unrealized_pnl },
    { k: "daily", label: "PnL diario", value: fmtSignedUsd(a.daily_pnl), tone: a.daily_pnl, sub: fmtPct(a.daily_pnl_pct), subTone: a.daily_pnl },
    { k: "winrate", label: "Tasa de acierto", value: `${a.win_rate}%`, sub: `${a.wins}/${a.total_trades} ganadoras` },
    { k: "trades", label: "Operaciones", value: a.total_trades, sub: `Profit factor ${a.profit_factor ?? "—"}` },
    { k: "drawdown", label: "Máx. drawdown", value: `${a.max_drawdown.toFixed(2)}%`, tone: a.max_drawdown > 0 ? -1 : 0, sub: `Pico ${fmtUsd(a.peak_equity, 0)}` },
  ];
  return (
    <div data-testid="kpi-strip" className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-[#1E293B] bg-[#1E293B] sm:grid-cols-4 xl:grid-cols-7">
      {items.map((it, i) => (
        <div key={it.k} data-testid={`kpi-${it.k}`} className="rise bg-[#0D111A] px-4 py-3.5" style={{ animationDelay: `${i * 40}ms` }}>
          <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">{it.label}</p>
          <p data-testid={`kpi-${it.k}-value`} className={`num mt-1.5 text-lg font-semibold md:text-xl ${it.tone != null ? pnlClass(it.tone) : "text-slate-50"}`}>
            {it.value}
          </p>
          <p className={`num mt-0.5 text-[11px] ${it.subTone != null ? pnlClass(it.subTone) : "text-slate-500"}`}>{it.sub}</p>
        </div>
      ))}
    </div>
  );
}
