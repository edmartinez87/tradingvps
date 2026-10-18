import { X } from "lucide-react";
import { SideBadge, Empty } from "./Panel";
import { fmtPrice, fmtSignedUsd, fmtUsd, fmtQty, pnlClass, STRATEGY_LABELS } from "@/lib/api";

const TH = ({ children, right }) => (
  <th className={`whitespace-nowrap px-3 py-2.5 font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500 ${right ? "text-right" : "text-left"}`}>{children}</th>
);
const TD = ({ children, right, className = "" }) => (
  <td className={`whitespace-nowrap px-3 py-2.5 ${right ? "text-right" : ""} ${className}`}>{children}</td>
);

export default function PositionsTable({ positions, onClose }) {
  if (!positions.length) return <Empty testId="positions-empty" text="Sin posiciones abiertas. El bot abrirá operaciones cuando una señal pase los filtros de riesgo y la IA." />;
  return (
    <div className="overflow-x-auto thin-scroll">
      <table data-testid="positions-table" className="w-full text-sm">
        <thead className="border-b border-[#1E293B]">
          <tr><TH>Símbolo</TH><TH>Lado</TH><TH right>Entrada</TH><TH right>Marca</TH><TH right>SL</TH><TH right>TP</TH><TH right>Tamaño</TH><TH right>Margen</TH><TH right>PnL</TH><TH right>Acción</TH></tr>
        </thead>
        <tbody className="num text-[12px]">
          {positions.map((p) => {
            const pct = p.margin ? (p.unrealized_pnl / p.margin) * 100 : 0;
            return (
              <tr key={p.id} data-testid={`position-row-${p.id}`} className="border-b border-[#1E293B]/60 transition-colors hover:bg-[#111827]">
                <TD>
                  <p className="font-display text-[13px] font-semibold text-slate-100">{p.symbol}</p>
                  <p className="text-[10px] text-slate-500">{STRATEGY_LABELS[p.strategy]} · {p.leverage}x</p>
                </TD>
                <TD><SideBadge side={p.side} /></TD>
                <TD right>{fmtPrice(p.entry_price)}</TD>
                <TD right className="text-slate-100">{fmtPrice(p.mark_price)}</TD>
                <TD right className="text-rose-400">{fmtPrice(p.sl)}{p.breakeven && <span className="ml-1 text-[9px] text-amber-400">BE</span>}</TD>
                <TD right className="text-emerald-400">{fmtPrice(p.tp)}</TD>
                <TD right>{fmtQty(p.qty)}</TD>
                <TD right>{fmtUsd(p.margin)}</TD>
                <TD right className={pnlClass(p.unrealized_pnl)}>
                  <span data-testid={`position-pnl-${p.id}`}>{fmtSignedUsd(p.unrealized_pnl)}</span>
                  <span className="block text-[10px]">{pct.toFixed(2)}%</span>
                </TD>
                <TD right>
                  <button data-testid={`close-position-${p.id}`} onClick={() => onClose(p.id)}
                    className="inline-flex items-center gap-1 rounded-sm border border-rose-500/40 px-2 py-1 font-mono text-[10px] uppercase text-rose-300 transition-colors hover:bg-rose-500/15">
                    <X className="h-3 w-3" /> Cerrar
                  </button>
                </TD>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export { TH, TD };
