import { SideBadge, Empty } from "./Panel";
import { TH, TD } from "./PositionsTable";
import { fmtPrice, fmtSignedUsd, fmtDateTime, pnlClass, REASON_LABELS, STRATEGY_LABELS } from "@/lib/api";

const REASON_CLS = {
  TP: "text-emerald-400 border-emerald-500/30",
  SL: "text-rose-400 border-rose-500/30",
  TRAILING: "text-amber-400 border-amber-500/30",
  MANUAL: "text-slate-300 border-slate-500/30",
};

export default function TradeHistory({ trades }) {
  if (!trades.length) return <Empty testId="trades-empty" text="Aún no hay operaciones cerradas." />;
  return (
    <div className="max-h-[420px] overflow-auto thin-scroll">
      <table data-testid="trades-table" className="w-full text-sm">
        <thead className="sticky top-0 border-b border-[#1E293B] bg-[#0D111A]">
          <tr><TH>Cierre</TH><TH>Símbolo</TH><TH>Lado</TH><TH right>Entrada</TH><TH right>Salida</TH><TH>Motivo</TH><TH right>Comisiones</TH><TH right>PnL</TH></tr>
        </thead>
        <tbody className="num text-[12px]">
          {trades.map((t) => (
            <tr key={t.id} data-testid={`trade-row-${t.id}`} className="border-b border-[#1E293B]/60 transition-colors hover:bg-[#111827]">
              <TD className="text-slate-400">{fmtDateTime(t.closed_at)}</TD>
              <TD>
                <p className="font-display text-[13px] font-semibold text-slate-100">{t.symbol}</p>
                <p className="text-[10px] text-slate-500">{STRATEGY_LABELS[t.strategy]}</p>
              </TD>
              <TD><SideBadge side={t.side} /></TD>
              <TD right>{fmtPrice(t.entry_price)}</TD>
              <TD right>{fmtPrice(t.exit_price)}</TD>
              <TD><span className={`rounded-sm border px-1.5 py-0.5 text-[10px] uppercase ${REASON_CLS[t.reason]}`}>{REASON_LABELS[t.reason]}</span></TD>
              <TD right className="text-slate-500">{t.fees.toFixed(2)}</TD>
              <TD right className={pnlClass(t.pnl)}>
                {fmtSignedUsd(t.pnl)}
                <span className="block text-[10px]">{t.pnl_pct > 0 ? "+" : ""}{t.pnl_pct.toFixed(2)}%</span>
              </TD>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
