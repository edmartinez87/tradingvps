import { Check, X, Loader2, AlertTriangle, Settings2, SlidersHorizontal, Zap, CheckCircle2, XCircle, Ban } from "lucide-react";
import { Button } from "@/components/ui/button";
import { fmtVal } from "@/components/bot/AiAdvice";
import { BOT_NAMES } from "@/fx/brand";

const KIND = {
  settings: { label: "Cambio de ajustes", Icon: SlidersHorizontal },
  config: { label: "Ajustes generales", Icon: Settings2 },
  action: { label: "Acción", Icon: Zap },
};
const STATUS = {
  applied: { label: "Aplicada", cls: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300", Icon: CheckCircle2 },
  discarded: { label: "Descartada", cls: "border-slate-600 bg-slate-800/60 text-slate-400", Icon: Ban },
  failed: { label: "No se pudo aplicar", cls: "border-rose-500/40 bg-rose-500/10 text-rose-300", Icon: XCircle },
};
const fmt = (k, v) => (Array.isArray(v) && !["disabled_strategies", "sessions_allowed", "symbols"].includes(k) ? v.join(", ") || "ninguno" : typeof v === "object" && v !== null && !Array.isArray(v) ? JSON.stringify(v) : fmtVal(k, v));

export function ProposalCard({ p, onResolve, busy }) {
  const kind = KIND[p.kind] || KIND.action;
  const pending = p.status === "pending";
  const st = STATUS[p.status];
  const diff = Object.entries(p.diff || {});
  return (
    <div data-testid={`proposal-card-${p.id}`} className={`mt-2 overflow-hidden rounded-md border ${pending ? "border-amber-400/60 bg-[#0D111A] shadow-[0_0_18px_rgba(247,166,0,0.12)]" : "border-[#1E293B] bg-[#0B0F17]"}`}>
      <div className="flex items-center gap-2 border-b border-[#1E293B] bg-gradient-to-r from-amber-500/15 to-transparent px-3 py-2">
        <kind.Icon className="h-3.5 w-3.5 text-amber-300" />
        <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-amber-200">{kind.label}</span>
        <span className="rounded-sm border border-[#1E293B] px-1.5 py-0.5 font-mono text-[9.5px] uppercase tracking-wider text-slate-400">{BOT_NAMES[p.bot] || p.bot}</span>
        {st && (
          <span data-testid={`proposal-status-${p.id}`} className={`ml-auto inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 font-mono text-[9.5px] font-semibold uppercase tracking-wider ${st.cls}`}>
            <st.Icon className="h-3 w-3" /> {st.label}
          </span>
        )}
        {pending && <span className="ml-auto font-mono text-[9.5px] uppercase tracking-wider text-amber-400/80">Requiere tu confirmación</span>}
      </div>
      <div className="space-y-2 px-3 py-2.5">
        {p.detail && <p data-testid={`proposal-detail-${p.id}`} className="text-[13px] font-semibold text-slate-100">{p.detail}</p>}
        {diff.length > 0 && (
          <div className="space-y-1">
            {diff.map(([k, v]) => (
              <div key={k} data-testid={`proposal-diff-${p.id}-${k}`} className="flex flex-wrap items-baseline gap-x-2 font-mono text-[11.5px]">
                <span className="text-slate-400">{p.labels?.[k] || k}:</span>
                <span className="text-slate-500 line-through">{fmt(k, v.antes)}</span>
                <span className="text-emerald-300">→ {fmt(k, v.despues)}</span>
              </div>
            ))}
          </div>
        )}
        {p.reason && <p className="text-[12px] italic leading-snug text-slate-400">{p.reason}</p>}
        {(p.warnings || []).map((w, i) => (
          <div key={i} className="flex gap-2 rounded-sm border border-amber-500/30 bg-amber-500/10 px-2 py-1.5 text-[11.5px] leading-snug text-amber-200">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {w}
          </div>
        ))}
        {pending ? (
          <div className="flex gap-2 pt-1">
            <Button data-testid={`proposal-apply-${p.id}`} size="sm" disabled={!!busy} onClick={() => onResolve(p.id, true)}
              className="h-8 bg-amber-500 font-mono text-[11px] font-bold uppercase tracking-wider text-[#07090E] hover:bg-amber-400">
              {busy === p.id ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Check className="mr-1.5 h-3.5 w-3.5" />} Aplicar
            </Button>
            <Button data-testid={`proposal-discard-${p.id}`} size="sm" variant="outline" disabled={!!busy} onClick={() => onResolve(p.id, false)}
              className="h-8 border-[#1E293B] bg-transparent font-mono text-[11px] uppercase tracking-wider text-slate-300 hover:bg-[#111827]">
              <X className="mr-1.5 h-3.5 w-3.5" /> Descartar
            </Button>
          </div>
        ) : (
          p.result && <p data-testid={`proposal-result-${p.id}`} className="font-mono text-[11px] text-slate-400">{p.result}</p>
        )}
      </div>
    </div>
  );
}
