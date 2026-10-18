import { useEffect, useRef, useState } from "react";
import { Activity } from "lucide-react";
import { Panel } from "./Panel";
import { fmtPrice, fmtPct, pnlClass } from "@/lib/api";

const TREND_CLS = {
  ALCISTA: "text-emerald-400 bg-emerald-500/10 border-emerald-500/25",
  BAJISTA: "text-rose-400 bg-rose-500/10 border-rose-500/25",
  NEUTRAL: "text-slate-400 bg-slate-500/10 border-slate-500/25",
};

function Row({ w, active, onSelect }) {
  const prev = useRef(w.price);
  const [flash, setFlash] = useState("");
  useEffect(() => {
    if (prev.current != null && w.price != null && w.price !== prev.current) {
      setFlash(w.price > prev.current ? "flash-up" : "flash-down");
      const t = setTimeout(() => setFlash(""), 700);
      prev.current = w.price;
      return () => clearTimeout(t);
    }
    prev.current = w.price;
  }, [w.price]);

  return (
    <button
      data-testid={`watchlist-row-${w.symbol}`}
      onClick={() => onSelect(w.symbol)}
      className={`group w-full border-b border-[#1E293B]/70 px-4 py-3 text-left transition-colors duration-150 ${flash} ${
        active ? "bg-amber-500/[0.06] shadow-[inset_2px_0_0_#F7A600]" : "hover:bg-[#111827]"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-display text-sm font-semibold text-slate-100">
          {w.symbol.replace("USDT", "")}<span className="text-slate-500">/USDT</span>
        </span>
        <span data-testid={`watchlist-price-${w.symbol}`} className="num text-sm text-slate-100">{fmtPrice(w.price)}</span>
      </div>
      <div className="mt-1.5 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          {w.trend && (
            <span className={`rounded-sm border px-1.5 py-px font-mono text-[9px] font-semibold uppercase tracking-wider ${TREND_CLS[w.trend]}`}>
              {w.trend}
            </span>
          )}
          {w.rsi != null && <span className="num text-[10px] text-slate-500">RSI {w.rsi}</span>}
          {w.signal && (
            <span data-testid={`watchlist-signal-${w.symbol}`} className="rounded-sm bg-amber-500 px-1.5 py-px font-mono text-[9px] font-bold uppercase text-[#07090E]">
              Señal {w.signal}
            </span>
          )}
        </div>
        <span className={`num text-[11px] ${pnlClass(w.change_pct)}`}>{fmtPct(w.change_pct)}</span>
      </div>
    </button>
  );
}

export default function Watchlist({ items, selected, onSelect }) {
  return (
    <Panel testId="watchlist-panel" title="Mercado en vivo" icon={Activity} className="lg:col-span-3" bodyClass="overflow-y-auto thin-scroll max-h-[540px]" delay={60}
      actions={<span className="font-mono text-[10px] uppercase tracking-wider text-slate-500">{items.length} pares</span>}>
      {items.map((w) => <Row key={w.symbol} w={w} active={w.symbol === selected} onSelect={onSelect} />)}
    </Panel>
  );
}
