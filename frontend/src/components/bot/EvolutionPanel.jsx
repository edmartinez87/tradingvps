import { useEffect, useState, useCallback } from "react";
import { GitBranch, Loader2, RefreshCw, Sparkles, ShieldCheck, User, FlaskConical, Cog } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { http, errMsg, fmtDateTime, fmtUsd, fmtSignedUsd, pnlClass } from "@/lib/api";
import { LABELS, fmtVal } from "./AiAdvice";

const ICON = { auto_review: Sparkles, optimize_all: Sparkles, optimizer: Sparkles, plan: Sparkles, walk_forward: FlaskConical, profile: ShieldCheck, manual: User, system: Cog };
const VERDICT = {
  MEJOR: { label: "Mejoró", cls: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300" },
  PEOR: { label: "Empeoró", cls: "border-rose-500/40 bg-rose-500/10 text-rose-300" },
  IGUAL: { label: "Sin cambio claro", cls: "border-slate-500/40 bg-slate-500/10 text-slate-300" },
  PENDIENTE: { label: "Pendiente de datos", cls: "border-amber-500/40 bg-amber-500/10 text-amber-300" },
};

const Metric = ({ label, before, after, fmt = (v) => v, cls }) => (
  <div className="flex items-baseline justify-between gap-2 font-mono text-[11px]">
    <span className="text-slate-500">{label}</span>
    <span><span className="text-slate-500">{fmt(before)}</span><span className="mx-1 text-slate-600">→</span><span className={`font-semibold ${cls ? cls(after) : "text-slate-200"}`}>{fmt(after)}</span></span>
  </div>
);

const Window = ({ ev, minTrades }) => {
  const v = VERDICT[ev.verdict];
  const pf = (x) => (x == null ? "—" : x);
  return (
    <div data-testid="evolution-window" className="rounded-sm border border-[#1E293B] bg-[#07090E] p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="font-mono text-[10px] uppercase tracking-wider text-slate-500">
          Rendimiento después · {ev.window_days} días{ev.ongoing ? " · en curso" : ""} · {ev.after.trades} ops
        </p>
        <span data-testid="evolution-verdict" className={`rounded-sm border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider ${v.cls}`}>{v.label}</span>
      </div>
      <div className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
        <Metric label="PnL" before={ev.before.pnl} after={ev.after.pnl} fmt={fmtSignedUsd} cls={pnlClass} />
        <Metric label="PnL medio/op" before={ev.before.avg_pnl} after={ev.after.avg_pnl} fmt={fmtSignedUsd} cls={pnlClass} />
        <Metric label="Acierto" before={ev.before.win_rate} after={ev.after.win_rate} fmt={(x) => `${x}%`} />
        <Metric label="Profit factor" before={ev.before.profit_factor} after={ev.after.profit_factor} fmt={pf} cls={(x) => (x == null ? "text-slate-400" : x >= 1 ? "text-emerald-400" : "text-rose-400")} />
      </div>
      <p className="mt-2 font-mono text-[10px] text-slate-500">
        Equidad {fmtUsd(ev.equity)} → {fmtUsd(ev.equity_end)} ({ev.equity_delta_pct > 0 ? "+" : ""}{ev.equity_delta_pct}%)
        {ev.verdict === "PENDIENTE" && ` · se necesitan ≥ ${minTrades} operaciones cerradas tras el cambio para juzgarlo`}
      </p>
    </div>
  );
};

const Event = ({ ev, minTrades }) => {
  const Icon = ICON[ev.source] || Cog;
  return (
    <li data-testid={`evolution-event-${ev.source}`} className="relative pl-8">
      <span className={`absolute left-0 top-1 flex h-5 w-5 items-center justify-center rounded-full border ${ev.ai ? "border-fuchsia-500/50 bg-fuchsia-500/15 text-fuchsia-300" : "border-[#1E293B] bg-[#0D111A] text-slate-400"}`}>
        <Icon className="h-3 w-3" />
      </span>
      <div className="space-y-2 rounded-md border border-[#1E293B] bg-[#0D111A] p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded-sm border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider ${ev.ai ? "border-fuchsia-500/40 bg-fuchsia-500/10 text-fuchsia-300" : "border-[#1E293B] text-slate-300"}`}>{ev.source_label}</span>
          <span className="font-mono text-[11px] text-slate-400">{fmtDateTime(ev.ts)}</span>
          <span className="font-mono text-[10px] text-slate-500">· {ev.mode} · {ev.total_trades} ops hasta entonces</span>
        </div>
        {ev.summary && <p data-testid="evolution-summary" className="text-[12px] leading-relaxed text-slate-300">{ev.summary}</p>}
        <ul data-testid="evolution-changes" className="space-y-0.5 text-[12px]">
          {Object.entries(ev.changes).map(([k, c]) => (
            <li key={k} className="flex flex-wrap gap-x-2">
              <span className="text-slate-400">{LABELS[k] || k}:</span>
              <span className="text-slate-500 line-through">{fmtVal(k, c.antes)}</span>
              <span className="text-emerald-300">→ {fmtVal(k, c.despues)}</span>
            </li>
          ))}
        </ul>
        <Window ev={ev} minTrades={minTrades} />
      </div>
    </li>
  );
};

export default function EvolutionPanel({ intro }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    setBusy(true);
    try { setData((await http.get("/evolution")).data); } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  return (
    <div data-testid="evolution-panel" className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-3xl text-[12px] leading-relaxed text-slate-400">
          {intro || "Cada cambio de configuración queda registrado con la equidad del momento: los que aplica la IA (revisión automática, optimizador, plan), la revalidación walk-forward, el perfil de riesgo y tus ajustes manuales. Debajo de cada uno verás cómo rindió el bot desde ese cambio hasta el siguiente, comparado con el tramo anterior."}
        </p>
        <Button data-testid="evolution-refresh" size="sm" variant="outline" onClick={load} disabled={busy} className="h-7 border-[#1E293B] bg-transparent font-mono text-[10px] uppercase tracking-wider text-slate-300">
          {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />} Actualizar
        </Button>
      </div>
      {!data ? (
        <p className="text-[12px] text-slate-500">Cargando…</p>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            {[["Cambios registrados", data.total, "evolution-total"], ["Aplicados por la IA", data.ai_changes, "evolution-ai"], ["Mejoraron", data.ai_better, "evolution-better", "text-emerald-400"],
              ["Empeoraron", data.ai_worse, "evolution-worse", "text-rose-400"], ["Pendientes de datos", data.ai_pending, "evolution-pending", "text-amber-300"]].map(([l, v, id, cls]) => (
              <div key={id} data-testid={id} className="min-w-[140px] flex-1 rounded-sm border border-[#1E293B] bg-[#0D111A] px-3 py-2.5">
                <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-slate-500">{l}</p>
                <p className={`num mt-1 text-base font-semibold ${cls || "text-slate-100"}`}>{v}</p>
              </div>
            ))}
          </div>
          {data.events.length === 0 ? (
            <p data-testid="evolution-empty" className="flex items-center gap-2 text-[12px] text-slate-500"><GitBranch className="h-4 w-4" /> Todavía no hay cambios registrados: aparecerán aquí en cuanto la IA, el walk-forward o tú modifiquéis la configuración.</p>
          ) : (
            <ol data-testid="evolution-timeline" className="relative space-y-3 border-l border-[#1E293B] pl-0 [&>li]:ml-[-1px]">
              {data.events.map((ev) => <Event key={ev.ts} ev={ev} minTrades={data.min_trades} />)}
            </ol>
          )}
        </>
      )}
    </div>
  );
}
