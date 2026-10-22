import { ArrowRight, CheckCircle2, Circle, AlertTriangle, CalendarCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { fmtUsd, fmtSignedUsd, pnlClass } from "@/lib/api";
import AiAdvice from "../AiAdvice";
import PlanContributions from "./PlanContributions";

const STATUS_CLS = {
  done: "border-emerald-500/40 bg-emerald-500/10 text-emerald-400",
  current: "border-amber-500/60 bg-amber-500/15 text-amber-300",
  pending: "border-[#1E293B] text-slate-500",
};
const fmtCrit = (c) => (c.fmt === "usd" ? fmtUsd(c.value, 0) : c.fmt === "pct" ? `${c.value}%` : c.value);
const fmtTarget = (c) => `${c.kind === "max" ? "≤" : "≥"} ${c.fmt === "usd" ? fmtUsd(c.target, 0) : c.fmt === "pct" ? `${c.target}%` : c.target}`;

export default function PlanCheckin({ checkin: c, onAdvance, onRefresh }) {
  const current = c.phases[c.phase];
  const tone = c.goal_met || c.ready_to_advance ? "border-emerald-500/40 bg-emerald-500/5" : c.warnings.length ? "border-rose-500/40 bg-rose-500/5" : "border-amber-500/30 bg-amber-500/5";
  return (
    <div data-testid="plan-checkin" className={`space-y-4 rounded-md border p-4 ${tone}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2">
          <CalendarCheck className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
          <div>
            <h4 className="font-display text-[12px] font-semibold uppercase tracking-[0.14em] text-slate-200">Chequeo del plan · resultados reales</h4>
            <p data-testid="plan-checkin-message" className={`mt-1 text-[13px] ${c.ready_to_advance || c.goal_met ? "text-emerald-300" : "text-slate-300"}`}>{c.message}</p>
            <p className="mt-0.5 font-mono text-[10px] uppercase tracking-wider text-slate-500">{c.days_running} días operando · próximo chequeo en {30 - (c.days_running % 30)} días</p>
          </div>
        </div>
        {c.ready_to_advance && (
          <Button data-testid="plan-advance-button" onClick={() => onAdvance(c.phase + 1, c.next_phase_risk)} className="h-9 bg-emerald-500 font-mono text-[11px] font-bold uppercase tracking-wider text-[#07090E] hover:bg-emerald-400">
            Avanzar a {c.next_phase_name} <ArrowRight className="ml-1.5 h-3.5 w-3.5" />
          </Button>
        )}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {c.phases.map((p) => (
          <span key={p.key} data-testid={`plan-checkin-phase-${p.key}`} className={`rounded-sm border px-2 py-1 font-mono text-[10px] uppercase tracking-wider ${STATUS_CLS[p.status]}`}>
            {p.index} · {p.name} {p.status === "done" ? "✓" : `${p.met}/${p.total}`}
          </span>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_260px]">
        <div data-testid="plan-checkin-criteria" className="space-y-2">
          {current.criteria.map((cr) => (
            <div key={cr.label} data-testid={`plan-criterion-${cr.label.replace(/[^a-z]/gi, "-").toLowerCase()}`} className="rounded-sm border border-[#1E293B] bg-[#0D111A] px-3 py-2">
              <div className="flex items-center justify-between gap-3 text-[12px]">
                <span className="flex items-center gap-2 text-slate-300">
                  {cr.met ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" /> : <Circle className="h-3.5 w-3.5 text-slate-600" />}{cr.label}
                </span>
                <span className="num"><span className={cr.met ? "text-emerald-400" : "text-slate-100"}>{fmtCrit(cr)}</span> <span className="text-slate-500">/ {fmtTarget(cr)}</span></span>
              </div>
              <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-[#1E293B]"><div className={`h-full ${cr.met ? "bg-emerald-500" : "bg-amber-500"}`} style={{ width: `${cr.pct}%` }} /></div>
            </div>
          ))}
        </div>
        <div className="space-y-2">
          <div data-testid="plan-checkin-last30" className="rounded-sm border border-[#1E293B] bg-[#0D111A] px-3 py-2.5">
            <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-slate-500">Últimos 30 días</p>
            <p className={`num mt-1 text-lg font-semibold ${pnlClass(c.last_30d.pnl)}`}>{fmtSignedUsd(c.last_30d.pnl)}</p>
            <p className="num text-[11px] text-slate-500">{c.last_30d.trades} ops · acierto {c.last_30d.win_rate}% · PF {c.last_30d.profit_factor ?? "—"} · retorno {c.last_30d.return_pct}%</p>
          </div>
          <PlanContributions c={c.contributions} />
          {c.warnings.map((w, i) => (
            <p key={i} data-testid={`plan-warning-${i}`} className="flex gap-2 rounded-sm border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[11.5px] leading-snug text-rose-200"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{w}</p>
          ))}
        </div>
      </div>
      <AiAdvice scope="plan" testId="plan-ai" label="Revisar plan y ajustar el bot con IA" onDone={onRefresh} />
    </div>
  );
}
