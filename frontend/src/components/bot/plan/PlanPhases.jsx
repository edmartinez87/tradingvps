import { fmtUsd } from "@/lib/api";
import { TH, TD } from "../PositionsTable";

const PHASE_CLS = {
  validacion: "text-slate-300 border-slate-500/40",
  semilla: "text-amber-400 border-amber-500/40",
  crecimiento: "text-emerald-400 border-emerald-500/40",
  consolidacion: "text-sky-400 border-sky-500/40",
  ingreso: "text-violet-400 border-violet-500/40",
};
const VALIDATION = {
  key: "validacion", name: "Validación en paper", risk: 1.0, start_month: 0, start_capital: 0,
  rule: "Sin dinero real. Dejar el bot operar 24/7 con IA activada durante 4–8 semanas.",
  advance: "≥ 60 operaciones cerradas, profit factor ≥ 1.3 y drawdown ≤ 10%. Si no se cumple, no pasar a real.",
};

export default function PlanPhases({ projection: p }) {
  if (!p.reachable) return null;
  const rows = [VALIDATION, ...p.timeline];
  return (
    <div data-testid="plan-phases" className="overflow-x-auto thin-scroll rounded-sm border border-[#1E293B]">
      <table className="w-full min-w-[900px] table-fixed text-sm">
        <colgroup><col className="w-[16%]" /><col className="w-[15%]" /><col className="w-[9%]" /><col className="w-[30%]" /><col className="w-[30%]" /></colgroup>
        <thead className="border-b border-[#1E293B] bg-[#0D111A]">
          <tr><TH>Fase</TH><TH>Comienza</TH><TH right>Riesgo/op</TH><TH>Regla de reinversión</TH><TH>Criterio para avanzar</TH></tr>
        </thead>
        <tbody className="text-[12px]">
          {rows.map((t, i) => (
            <tr key={t.key} data-testid={`plan-phase-${t.key}`} className="border-b border-[#1E293B]/60 align-top">
              <TD>
                <span className={`inline-block rounded-sm border px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wider ${PHASE_CLS[t.key]}`}>Fase {i}</span>
                <p className="mt-1 font-display text-[13px] font-semibold text-slate-100">{t.name}</p>
              </TD>
              <TD className="num text-slate-300">
                {t.key === "validacion" ? "Hoy" : t.start_month === 0 ? "Mes 1 (al pasar a real)" : `Mes ${t.start_month}`}
                {t.key !== "validacion" && <span className="block text-[10px] text-slate-500">capital {fmtUsd(t.start_capital, 0)}</span>}
              </TD>
              <TD right className="num text-slate-100">{t.key === "validacion" ? "1% (paper)" : `${t.risk}%`}</TD>
              <td className="whitespace-normal px-3 py-2.5 leading-snug text-slate-300">{t.rule}</td>
              <td className="whitespace-normal px-3 py-2.5 leading-snug text-slate-400">{t.advance}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
