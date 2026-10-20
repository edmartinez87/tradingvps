import { Loader2, CalendarClock, RefreshCw, Scissors } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { http, errMsg, fmtDateTime } from "@/lib/api";
import { TH, TD } from "../PositionsTable";
import { VerdictBadge } from "./WalkForward";

const sign = (v, d = 2) => (v == null ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(d)}`);

export default function WalkForwardAuto({ check, running, step, onRun, appliedCount, autoRemove, onAutoRemove }) {
  const rows = Object.entries(check?.results || {});
  const removed = Object.keys(check?.removed || {});
  const toggle = async (v) => {
    try {
      await http.put("/config", { wf_auto_remove: v });
      onAutoRemove(v);
      toast.success(v ? "Borrado automático activado" : "Borrado automático desactivado: solo avisará");
    } catch (e) {
      toast.error(errMsg(e));
    }
  };
  return (
    <div data-testid="wf-auto-card" className="rounded-md border border-[#1E293B] bg-[#0D111A]/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-[240px] flex-1">
          <p className="flex items-center gap-1.5 font-display text-[15px] font-bold text-slate-100"><CalendarClock className="h-4 w-4 text-sky-300" /> Revalidación semanal automática</p>
          <p className="mt-1 text-[12px] leading-relaxed text-slate-400">
            Cada lunes a las 07:00 UTC el bot repite el walk-forward en los pares que tienen SL/TP optimizados aplicados: simula a ciegas esos mismos SL/TP en los tramos fuera de muestra
            {autoRemove ? ", quita automáticamente los que salgan sobreajustados y te avisa del cambio por Telegram." : " y te avisa por Telegram si alguno pasa a sobreajustado."}
            {check ? <> Última revalidación: <span className="text-slate-200">{fmtDateTime(check.ran_at)}</span> ({check.source === "auto" ? "automática" : "manual"}).</> : " Aún no se ha ejecutado."}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label data-testid="wf-auto-remove-label" className="flex cursor-pointer items-center gap-2 rounded-sm border border-[#1E293B] px-3 py-2 font-mono text-[10px] uppercase tracking-wider text-slate-300">
            <Scissors className="h-3.5 w-3.5 text-amber-300" /> Quitar sobreajustados
            <Switch data-testid="wf-auto-remove-switch" checked={!!autoRemove} onCheckedChange={toggle} />
          </label>
          <Button data-testid="wf-auto-run-button" onClick={onRun} disabled={running} variant="outline"
            className="h-9 border-[#1E293B] bg-transparent font-mono text-[11px] uppercase tracking-wider text-slate-200 hover:bg-[#111827] disabled:opacity-50">
            {running ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="mr-1.5 h-3.5 w-3.5" />}
            {running ? (step || "Revalidando...") : "Revalidar ahora"}
          </Button>
        </div>
      </div>
      {removed.length > 0 && (
        <p data-testid="wf-auto-removed" className="mt-3 rounded-sm border border-amber-500/30 bg-amber-500/[0.06] px-3 py-2 text-[12px] text-amber-200">
          <Scissors className="mr-1 inline h-3.5 w-3.5" /> En la última revalidación se quitaron los SL/TP optimizados de <span className="font-semibold">{removed.join(", ")}</span> por sobreajuste: esos pares vuelven a los valores por defecto de cada estrategia.
        </p>
      )}
      {appliedCount === 0 && !rows.length && (
        <p data-testid="wf-auto-empty" className="mt-3 text-[12px] text-slate-500">Ningún par activo tiene parámetros aplicados: no hay nada que revalidar. Aplica un óptimo desde «Optimizar par» para que entre en la revisión semanal.</p>
      )}
      {rows.length > 0 && (
        <div data-testid="wf-auto-table" className="mt-3 overflow-x-auto thin-scroll rounded-sm border border-[#1E293B]">
          <table className="w-full text-sm">
            <thead className="border-b border-[#1E293B] bg-[#0D111A]">
              <tr><TH>Par</TH><TH>Parámetros revisados</TH><TH>Veredicto (SL/TP aplicados)</TH><TH right>WFE</TH><TH right>Exp. OOS (R)</TH><TH right>Ops OOS</TH><TH right>Base OOS (R)</TH><TH>Re-optimización</TH></tr>
            </thead>
            <tbody className="num text-[12px]">
              {rows.map(([sym, r]) => (
                <tr key={sym} data-testid={`wf-auto-row-${sym}`} className="border-b border-[#1E293B]/60">
                  <TD className="font-display text-[13px] font-semibold text-slate-100">{sym}</TD>
                  <TD className="text-slate-300">
                    {r.params ? `SL ${r.params.sl_atr}× · TP ${r.params.tp_atr}× · ATR ${r.params.atr_period ?? 14}` : "—"}
                    {r.removed && <span data-testid={`wf-auto-removed-${sym}`} className="ml-1.5 rounded-sm border border-amber-500/40 px-1 font-mono text-[9px] uppercase text-amber-300">quitados</span>}
                  </TD>
                  <TD>
                    <VerdictBadge verdict={r.verdict} testId={`wf-auto-verdict-${sym}`} />
                    {r.changed && <span className="ml-1.5 font-mono text-[10px] text-slate-500">antes {r.previous_verdict}</span>}
                  </TD>
                  <TD right className={r.wfe == null ? "text-slate-500" : r.wfe >= 0.5 ? "text-emerald-400" : "text-rose-400"}>{r.wfe == null ? "—" : r.wfe.toFixed(2)}</TD>
                  <TD right className={`font-semibold ${r.oos.expectancy_r > 0 ? "text-emerald-400" : "text-rose-400"}`}>{sign(r.oos.expectancy_r, 3)}</TD>
                  <TD right>{r.oos.trades}</TD>
                  <TD right className="text-slate-400">{sign(r.baseline_oos.expectancy_r, 3)}</TD>
                  <TD>{r.process_verdict ? <VerdictBadge verdict={r.process_verdict} testId={`wf-auto-process-${sym}`} /> : <span className="text-slate-600">—</span>}</TD>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
