import { fmtUsd, fmtSignedUsd, fmtPct, pnlClass } from "@/lib/api";

export default function KpiStrip({ account: a }) {
  const nd = a.net_deposits ?? 0;
  const items = [
    { k: "balance", label: "Balance", value: fmtUsd(a.balance), sub: `Disponible ${fmtUsd(a.available)}` },
    { k: "equity", label: "Equidad", value: fmtUsd(a.equity), sub: `Retorno ${fmtPct(a.total_return_pct)}${nd ? ` · aportes ${fmtSignedUsd(nd, 0)}` : ""}`, subTone: a.total_return_pct,
      hint: `PnL total ${fmtSignedUsd(a.total_pnl ?? a.equity - a.initial_balance)} sobre el capital aportado ${fmtUsd(a.capital ?? a.initial_balance)} (inicial ${fmtUsd(a.initial_balance)}${nd ? ` + aportes netos ${fmtSignedUsd(nd)}` : ""}). Los depósitos y retiros no cuentan como ganancia ni pérdida.` },
    { k: "unrealized", label: "PnL no realizado", value: fmtSignedUsd(a.unrealized_pnl), tone: a.unrealized_pnl, sub: fmtPct(a.unrealized_pct), subTone: a.unrealized_pnl },
    { k: "daily", label: "PnL diario", value: fmtSignedUsd(a.daily_pnl), tone: a.daily_pnl, sub: fmtPct(a.daily_pnl_pct), subTone: a.daily_pnl, hint: "Desde el inicio del día UTC · los depósitos y retiros del día no cuentan" },
    { k: "winrate", label: "Tasa de acierto", value: `${a.win_rate}%`, sub: `${a.wins}/${a.total_trades} ganadoras` },
    { k: "trades", label: "Operaciones", value: a.total_trades, sub: `Profit factor ${a.profit_factor ?? "—"}` },
    { k: "drawdown", label: "Máx. drawdown", value: `${a.max_drawdown.toFixed(2)}%`, tone: a.max_drawdown > 0 ? -1 : 0, sub: `Pico ${fmtUsd(a.peak_equity, 0)}`, hint: "Caída máxima desde el pico de equidad, ajustada por depósitos y retiros" },
  ];
  return (
    <div data-testid="kpi-strip" className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-[#1E293B] bg-[#1E293B] sm:grid-cols-4 xl:grid-cols-7">
      {items.map((it, i) => (
        <div key={it.k} data-testid={`kpi-${it.k}`} title={it.hint} className={`rise bg-[#0D111A] px-4 py-3.5 last:col-span-2 xl:last:col-span-1 ${it.hint ? "cursor-help" : ""}`} style={{ animationDelay: `${i * 40}ms` }}>
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
