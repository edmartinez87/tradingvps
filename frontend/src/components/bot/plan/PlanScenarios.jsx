import { fmtUsd } from "@/lib/api";

export const fmtMonths = (m) => {
  if (m == null) return "No alcanzable";
  if (m === 0) return "Ya alcanzado";
  const y = Math.floor(m / 12), r = m % 12;
  return [y ? `${y} año${y > 1 ? "s" : ""}` : "", r ? `${r} mes${r > 1 ? "es" : ""}` : ""].filter(Boolean).join(" ");
};

export default function PlanScenarios({ scenarios, selected, onSelect, target }) {
  return (
    <div data-testid="plan-scenarios" className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {scenarios.map((s) => {
        const active = s.key === selected;
        const dead = s.rate_pct == null || s.rate_pct <= 0;
        return (
          <button key={s.key} type="button" data-testid={`plan-scenario-${s.key}`} onClick={() => !dead && onSelect(s.key)} disabled={dead}
            className={`rounded-md border p-3 text-left transition-colors ${active ? "border-amber-500 bg-amber-500/5" : "border-[#1E293B] bg-[#0D111A] hover:border-slate-600"} ${dead ? "cursor-not-allowed opacity-60" : ""}`}>
            <div className="flex items-baseline justify-between gap-2">
              <p className={`font-display text-[13px] font-semibold uppercase tracking-wider ${active ? "text-amber-400" : "text-slate-200"}`}>{s.name}</p>
              <p data-testid={`plan-scenario-${s.key}-rate`} className="num text-base font-semibold text-slate-100">{s.rate_pct == null ? "—" : `${s.rate_pct}%`}<span className="text-[10px] text-slate-500">/mes</span></p>
            </div>
            <p className="mt-1 text-[11px] leading-snug text-slate-500">{s.desc}</p>
            <div className="mt-3 space-y-1 border-t border-[#1E293B] pt-2 font-mono text-[11px]">
              <div className="flex justify-between"><span className="text-slate-500">Tiempo a {fmtUsd(target, 0)}/mes</span><span data-testid={`plan-scenario-${s.key}-time`} className={`font-semibold ${s.reachable ? "text-emerald-400" : "text-rose-400"}`}>{dead ? "Sistema no rentable" : fmtMonths(s.months)}</span></div>
              <div className="flex justify-between"><span className="text-slate-500">Capital necesario</span><span className="text-slate-200">{s.target_capital ? fmtUsd(s.target_capital, 0) : "—"}</span></div>
              {s.total_deposited > 0 && <div className="flex justify-between"><span className="text-slate-500">Aportado</span><span className="text-slate-200">{fmtUsd(s.total_deposited, 0)}</span></div>}
            </div>
          </button>
        );
      })}
    </div>
  );
}
