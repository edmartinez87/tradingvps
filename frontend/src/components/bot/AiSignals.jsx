import { Sparkles } from "lucide-react";
import { Panel, SideBadge, Empty } from "./Panel";
import { fmtPrice, fmtTime, STRATEGY_LABELS } from "@/lib/api";

const DECISION_CLS = {
  APROBADA: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  RECHAZADA: "bg-rose-500/10 text-rose-400 border-rose-500/30",
  ERROR: "bg-orange-500/10 text-orange-400 border-orange-500/30",
  SIN_IA: "bg-slate-500/10 text-slate-300 border-slate-500/30",
  BLOQUEADA: "bg-amber-500/10 text-amber-300 border-amber-500/30",
  NOTICIAS: "bg-fuchsia-500/10 text-fuchsia-300 border-fuchsia-500/30",
  FUNDING: "bg-cyan-500/10 text-cyan-300 border-cyan-500/30",
  MERCADO: "bg-slate-500/10 text-slate-300 border-slate-500/30",
  SESION: "bg-sky-500/10 text-sky-300 border-sky-500/30",
  REGIMEN: "bg-indigo-500/10 text-indigo-300 border-indigo-500/30",
  ROTACION: "bg-teal-500/10 text-teal-300 border-teal-500/30",
  EXPOSICION: "bg-orange-500/10 text-orange-300 border-orange-500/30",
  ROLLOVER: "bg-slate-500/10 text-slate-300 border-slate-500/30",
  VOLATILIDAD: "bg-fuchsia-500/10 text-fuchsia-300 border-fuchsia-500/30",
  ESTACIONAL: "bg-cyan-500/10 text-cyan-300 border-cyan-500/30",
  REGIMEN_USD: "bg-indigo-500/10 text-indigo-300 border-indigo-500/30",
  FOMC: "bg-red-500/10 text-red-300 border-red-500/30",
};

function SignalCard({ s }) {
  return (
    <article data-testid={`ai-signal-${s.id}`} className="border-b border-[#1E293B]/70 px-4 py-3.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-display text-sm font-semibold text-slate-100">{s.symbol}</span>
          <SideBadge side={s.side} />
          <span className="font-mono text-[10px] text-slate-500">{s.timeframe}</span>
        </div>
        <span data-testid={`ai-decision-${s.id}`} className={`rounded-sm border px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider ${DECISION_CLS[s.ai_decision]}`}>
          {s.ai_decision === "SIN_IA" ? "Sin IA" : s.ai_decision === "SESION" ? "Sesión" : s.ai_decision}
        </span>
      </div>
      <p className="mt-1 font-mono text-[10px] text-slate-500">
        {STRATEGY_LABELS[s.strategy]} · {fmtPrice(s.price)} · SL {fmtPrice(s.sl)} · TP {fmtPrice(s.tp)} · {fmtTime(s.created_at)}
      </p>
      {!["SIN_IA", "ERROR", "BLOQUEADA", "NOTICIAS", "FUNDING", "MERCADO", "SESION", "REGIMEN", "ROTACION", "EXPOSICION", "ROLLOVER", "VOLATILIDAD", "ESTACIONAL", "REGIMEN_USD", "FOMC"].includes(s.ai_decision) && (
        <div className="mt-2 flex items-center gap-2">
          <div className="h-1 flex-1 overflow-hidden rounded-full bg-[#1E293B]">
            <div className="h-full bg-purple-500" style={{ width: `${s.ai_confidence}%` }} />
          </div>
          <span className="num text-[10px] text-purple-300">{s.ai_confidence}%</span>
          <span className="font-mono text-[10px] uppercase text-slate-400">Riesgo {s.ai_risk}</span>
        </div>
      )}
      {s.ai_reasoning && <p className="mt-2 text-[12px] leading-relaxed text-slate-300">{s.ai_reasoning}</p>}
      {s.note && <p className="mt-1.5 text-[11px] text-orange-300">{s.note}</p>}
      <div className="mt-2 flex flex-wrap gap-1">
        {s.reasons.map((r) => (
          <span key={r} className="rounded-sm bg-[#111827] px-1.5 py-0.5 text-[10px] text-slate-400">{r}</span>
        ))}
        {s.executed && <span className="rounded-sm bg-amber-500 px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase text-[#07090E]">Ejecutada</span>}
      </div>
    </article>
  );
}

const UsageChip = ({ usage, ai }) => {
  if (!usage) return null;
  const parts = [`${usage.signals} señales`, `${usage.news} noticias`, ...(usage.news_trades ? [`${usage.news_trades} op. noticias`] : []), `${usage.reviews} revisiones`];
  const title = `Llamadas a la IA de hoy (UTC) de este bot: ${parts.join(" · ")}${usage.skipped_news ? ` · ${usage.skipped_news} análisis de noticias ahorrados (sin titulares nuevos)` : ""} · ambos bots: ${usage.total_all}`;
  return (
    <span data-testid="ai-usage-chip" title={title} className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider">
      <span className="rounded-sm border border-[#1E293B] bg-[#0D111A] px-1.5 py-0.5 text-slate-300">IA hoy <span className="num text-amber-300">{usage.total}</span>
        {usage.skipped_news ? <span className="text-emerald-400"> · {usage.skipped_news} ahorradas</span> : null}</span>
      {ai?.label && (ai.health?.ok === false
        ? <span data-testid="ai-model-badge" title={ai.health.error} className="rounded-sm border border-rose-500/50 bg-rose-500/15 px-1.5 py-0.5 text-rose-300">{ai.label} · sin servicio</span>
        : <span data-testid="ai-model-badge" className="rounded-sm border border-purple-500/30 bg-purple-500/10 px-1.5 py-0.5 text-purple-300">{ai.label}</span>)}
    </span>
  );
};

export default function AiSignals({ signals, ai, usage }) {
  return (
    <Panel testId="ai-signals-panel" title="Evaluación IA" icon={Sparkles} className="lg:col-span-4" bodyClass="max-h-[480px] overflow-y-auto thin-scroll" delay={260}
      actions={<UsageChip usage={usage} ai={ai} />}>
      {signals.length ? signals.map((s) => <SignalCard key={s.id} s={s} />) : (
        <Empty testId="ai-signals-empty" text="Cuando el bot detecte una señal, la IA la evaluará aquí con su razonamiento." />
      )}
    </Panel>
  );
}
