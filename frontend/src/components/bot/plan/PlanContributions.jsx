import { PiggyBank } from "lucide-react";
import { fmtUsd, fmtSignedUsd, pnlClass } from "@/lib/api";

const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const label = (m) => `${MONTHS[Number(m.slice(5, 7)) - 1]} ${m.slice(2, 4)}`;
const chip = (m) => (m.met ? "border-emerald-500/40 text-emerald-400" : m.current ? "border-amber-500/50 text-amber-300" : "border-rose-500/30 text-rose-300/80");

// Real deposits (paper or detected at the broker) against the monthly contribution committed in the growth plan.
export default function PlanContributions({ c }) {
  if (!c) return null;
  const tm = c.this_month;
  const pct = c.target > 0 ? Math.min(100, (tm.deposited / c.target) * 100) : 0;
  return (
    <div data-testid="plan-contributions" className="rounded-sm border border-[#1E293B] bg-[#0D111A] px-3 py-2.5">
      <p className="flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-[0.16em] text-slate-500"><PiggyBank className="h-3 w-3 text-amber-300" /> Aportes del plan</p>
      {c.target > 0 ? (
        <>
          <p data-testid="plan-contrib-month" className="num mt-1 text-sm font-semibold text-slate-100">{fmtUsd(tm.deposited)} <span className="text-[11px] text-slate-500">/ {fmtUsd(c.target)} este mes{tm.met ? " · cumplido" : ""}</span></p>
          <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-[#1E293B]"><div className={`h-full ${tm.met ? "bg-emerald-500" : "bg-amber-500"}`} style={{ width: `${pct}%` }} /></div>
          <div data-testid="plan-contrib-months" className="mt-2 flex flex-wrap gap-1">
            {c.months.map((m) => (
              <span key={m.month} data-testid={`plan-contrib-${m.month}`} title={`${label(m.month)}: ${fmtUsd(m.deposited)} de ${fmtUsd(m.target)}${m.withdrawn ? ` · retiros ${fmtUsd(m.withdrawn)}` : ""}`}
                className={`rounded-sm border px-1.5 py-0.5 font-mono text-[9px] uppercase ${chip(m)}`}>{label(m.month)} {m.met ? "✓" : m.current ? "…" : "✗"}</span>
            ))}
          </div>
          <p data-testid="plan-contrib-summary" className="mt-1.5 text-[11px] text-slate-500">{c.months_met} de {c.months_total} meses cumplidos · aportado {fmtUsd(c.total_deposited)} de {fmtUsd(c.expected_to_date)} previstos{c.total_withdrawn ? ` · retiros ${fmtUsd(c.total_withdrawn)}` : ""}</p>
          <p data-testid="plan-contrib-vs" className="text-[11px] text-slate-500">Capital vs plan a estas alturas: <span className={`num ${pnlClass(c.capital_vs_plan)}`}>{fmtSignedUsd(c.capital_vs_plan)}</span> <span className="text-slate-600">(plan {fmtUsd(c.expected_capital, 0)} al mes {c.elapsed_months})</span></p>
        </>
      ) : (
        <p data-testid="plan-contrib-none" className="mt-1 text-[11px] leading-snug text-slate-500">{c.message}{c.total_deposited || c.total_withdrawn ? "" : " Fija un aporte mensual en la calculadora de arriba para seguirlo aquí."}</p>
      )}
    </div>
  );
}
