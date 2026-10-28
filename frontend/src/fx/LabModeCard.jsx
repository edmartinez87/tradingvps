import { useState } from "react";
import { FlaskConical, Loader2, Power, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Panel } from "@/components/bot/Panel";
import { BTN, BTN_OUT } from "@/components/bot/admin/SecuritySection";
import { fmtSignedUsd, fmtDateTime, REASON_LABELS } from "@/lib/api";
import { LABELS } from "@/components/bot/AiAdvice";

const Stat = ({ label, value, cls = "text-slate-100", testId }) => (
  <div className="rounded-sm border border-[#1E293B] bg-[#0B1220] px-3 py-2">
    <p className="font-mono text-[9.5px] uppercase tracking-[0.16em] text-slate-500">{label}</p>
    <p data-testid={testId} className={`num mt-0.5 text-sm font-semibold ${cls}`}>{value}</p>
  </div>
);

export default function LabModeCard({ lab, onStart, onStop }) {
  const [busy, setBusy] = useState(false);
  if (!lab) return null;
  const run = async (fn) => { setBusy(true); try { await fn(); } finally { setBusy(false); } };
  const st = lab.stats;
  const reasons = st ? Object.entries(st.reasons || {}).map(([k, v]) => `${REASON_LABELS[k] || k} ${v}`).join(" · ") : "";
  return (
    <Panel testId="lab-card" title={`Modo laboratorio · solo ${lab.name}`} icon={FlaskConical} bodyClass="p-4 space-y-3"
      actions={lab.active
        ? <span data-testid="lab-active-badge" className="inline-flex items-center gap-1.5 rounded-sm border border-teal-400/50 bg-teal-500/10 px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider text-teal-300"><span className="pulse-dot bg-teal-300" /> Activo desde {fmtDateTime(lab.since)}</span>
        : <span data-testid="lab-inactive-badge" className="rounded-sm border border-[#1E293B] px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-slate-500">Inactivo</span>}>
      <p className="text-[12px] leading-relaxed text-slate-400">{lab.summary}</p>
      {lab.active && st && (
        <div data-testid="lab-stats" className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
          <Stat label="Operaciones" value={st.trades} testId="lab-stat-trades" />
          <Stat label="Acierto" value={`${st.win_rate}%`} cls={st.win_rate >= 50 ? "text-emerald-400" : "text-slate-100"} />
          <Stat label="PnL" value={fmtSignedUsd(st.pnl)} cls={st.pnl > 0 ? "text-emerald-400" : st.pnl < 0 ? "text-rose-400" : "text-slate-100"} testId="lab-stat-pnl" />
          <Stat label="Pips netos" value={st.pips} />
          <Stat label="Profit factor" value={st.profit_factor || "—"} />
          <Stat label="Cierres por cruce" value={st.cross_exits} testId="lab-stat-cross" />
          <Stat label="Abiertas" value={st.open} />
        </div>
      )}
      {lab.active && reasons && <p className="font-mono text-[10.5px] text-slate-500">Motivos de cierre: {reasons}</p>}
      {lab.active && lab.altered?.length > 0 && (
        <p data-testid="lab-altered-warning" className="flex items-start gap-1.5 rounded-sm border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-200">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>Ajustes del laboratorio cambiados a mano: {lab.altered.map((k) => LABELS[k] || k).join(", ")}. La data deja de ser «solo Cruce EMA 10/20» hasta que reapliques el preset (Desactivar y volver a activar).</span>
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {lab.active ? (
          <Button data-testid="lab-stop-button" variant="outline" disabled={busy} onClick={() => run(onStop)} className={BTN_OUT}>
            {busy ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Power className="mr-1.5 h-3.5 w-3.5" />} Desactivar y restaurar ajustes
          </Button>
        ) : (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button data-testid="lab-start-button" disabled={busy} className={BTN}><FlaskConical className="mr-1.5 h-3.5 w-3.5" /> Activar laboratorio</Button>
            </AlertDialogTrigger>
            <AlertDialogContent className="border-[#1E293B] bg-[#0D111A]">
              <AlertDialogHeader>
                <AlertDialogTitle className="font-display text-teal-200">Activar el modo laboratorio</AlertDialogTitle>
                <AlertDialogDescription className="space-y-2 text-slate-400">
                  <span className="block">{lab.summary}</span>
                  <span className="block">Tus ajustes actuales se guardan y se restauran al desactivarlo. Aplicar un perfil de riesgo termina el laboratorio: el perfil define los ajustes y solo se restauran noticias y revisión IA automática.</span>
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel data-testid="lab-start-cancel" className={BTN_OUT}>Cancelar</AlertDialogCancel>
                <AlertDialogAction data-testid="lab-start-confirm" onClick={() => run(onStart)} className={BTN}>Activar</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
        <span className="font-mono text-[10px] uppercase tracking-wider text-slate-600">Rendimiento → Por estrategia y el Historial recogen la data · solo en paper</span>
      </div>
    </Panel>
  );
}
