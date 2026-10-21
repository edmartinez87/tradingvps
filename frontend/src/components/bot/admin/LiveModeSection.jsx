import { useCallback, useEffect, useState } from "react";
import { Rocket, Loader2, CheckCircle2, XCircle, CircleDashed, Undo2, AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Panel } from "../Panel";
import { http, errMsg, fmtUsd, fmtDateTime } from "@/lib/api";
import { INPUT, BTN_OUT } from "./SecuritySection";

export const BYBIT_LIVE_LABELS = {
  exchange: "Bybit",
  liveDesc: (data) => <>Operando con dinero real en Bybit <span className="text-slate-200">{data.env}</span> desde {fmtDateTime(data.live_since)}. Las órdenes se envían con SL/TP adjuntos y el trailing stop se actualiza en el exchange.</>,
  paperDesc: () => <>Deja el bot en paper hasta completar la Fase 0 del plan. Cuando los requisitos estén en verde, pasa a real: el bot usará la misma estrategia, el mismo riesgo y la equidad real de tu cuenta Bybit para dimensionar cada orden.</>,
  dialogDesc: (data) => <>El bot enviará órdenes reales a Bybit <b className="text-slate-200">{data.env}</b> con una equidad verificada de <b className="text-slate-200">{fmtUsd(data.verified_equity || 0)}</b>. Riesgo por operación, apalancamiento y límites de la configuración actual se aplican tal cual.</>,
  resetLabel: "Reiniciar estadísticas con la equidad real de Bybit",
};

export default function LiveModeSection({ config, refresh, labels = BYBIT_LIVE_LABELS }) {
  const [data, setData] = useState(null);
  const [confirm, setConfirm] = useState("");
  const [resetStats, setResetStats] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => http.get("/mode").then((r) => setData(r.data)).catch(() => {}), []);
  useEffect(() => { load(); const id = setInterval(load, 5000); return () => clearInterval(id); }, [load, config]);

  const switchMode = async (mode) => {
    setBusy(true);
    try {
      const { data: d } = await http.post("/mode", { mode, confirm, reset_stats: resetStats });
      setData(d);
      setConfirm("");
      toast.success(mode === "live" ? "MODO REAL activado · inicia el bot cuando quieras" : "Vuelta a modo paper");
      refresh?.();
    } catch (e) {
      toast.error(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  if (!data) return <Panel testId="livemode-section" title="Modo de operación" icon={Rocket} bodyClass="p-4"><Loader2 className="h-4 w-4 animate-spin text-slate-500" /></Panel>;
  const live = data.mode === "live";
  return (
    <Panel testId="livemode-section" title="Modo de operación" icon={Rocket} bodyClass="p-4 space-y-3"
      actions={<span data-testid="livemode-badge" className={`rounded-sm border px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider ${live ? "border-rose-500/50 bg-rose-500/10 text-rose-300" : "border-amber-500/40 bg-amber-500/10 text-amber-300"}`}>{live ? `REAL · ${data.env}` : "PAPER"}</span>}>
      <p className="text-[12px] leading-relaxed text-slate-400">
        {live ? labels.liveDesc(data) : labels.paperDesc(data)}
      </p>
      <ul data-testid="livemode-checklist" className="space-y-1.5">
        {data.checks.map((c) => (
          <li key={c.key} data-testid={`livemode-check-${c.key}`} className="flex items-center justify-between gap-3 rounded-sm border border-[#1E293B] bg-[#0D111A] px-3 py-2 text-[12px]">
            <span className="flex items-center gap-2 text-slate-200">
              {c.ok ? (c.warn ? <AlertTriangle className="h-3.5 w-3.5 text-amber-400" /> : <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />) : c.required ? <XCircle className="h-3.5 w-3.5 text-rose-400" /> : <CircleDashed className="h-3.5 w-3.5 text-amber-400" />}
              {c.label}{!c.required && <span className="font-mono text-[9px] uppercase tracking-wider text-slate-500">recomendado</span>}
            </span>
            {c.detail && <span className={`num text-[11px] ${c.warn ? "text-amber-300" : "text-slate-500"}`}>{c.detail}</span>}
          </li>
        ))}
      </ul>
      {live ? (
        <Button data-testid="livemode-paper-button" variant="outline" onClick={() => switchMode("paper")} disabled={busy} className={BTN_OUT}>
          {busy ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Undo2 className="mr-1.5 h-3.5 w-3.5" />} Volver a modo paper
        </Button>
      ) : (
        <AlertDialog onOpenChange={(o) => !o && setConfirm("")}>
          <AlertDialogTrigger asChild>
            <Button data-testid="livemode-go-live-button" disabled={!data.can_go_live || busy} className="h-10 bg-rose-500 font-mono text-[12px] font-bold uppercase tracking-wider text-white hover:bg-rose-400 disabled:opacity-40">
              <Rocket className="mr-1.5 h-4 w-4" /> Pasar a modo REAL
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent data-testid="livemode-dialog" className="border-rose-500/30 bg-[#0D111A]">
            <AlertDialogHeader>
              <AlertDialogTitle className="font-display text-rose-300">Activar trading con dinero real</AlertDialogTitle>
              <AlertDialogDescription className="space-y-2 text-slate-400">
                <span className="block">{labels.dialogDesc(data)}</span>
                <span className="block">Escribe <b className="font-mono text-rose-300">REAL</b> para confirmar.</span>
              </AlertDialogDescription>
            </AlertDialogHeader>
            <Input data-testid="livemode-confirm-input" value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="REAL" className={`${INPUT} uppercase`} />
            <label className="flex items-center justify-between gap-3 rounded-sm border border-[#1E293B] px-3 py-2 text-[12px] text-slate-200">
              <span>{labels.resetLabel}<span className="block text-[11px] text-slate-500">Borra historial paper, posiciones y señales; las estadísticas empiezan desde el capital real.</span></span>
              <Switch data-testid="livemode-reset-switch" checked={resetStats} onCheckedChange={setResetStats} />
            </label>
            <AlertDialogFooter>
              <AlertDialogCancel data-testid="livemode-cancel">Cancelar</AlertDialogCancel>
              <AlertDialogAction data-testid="livemode-confirm-button" disabled={confirm.trim().toUpperCase() !== "REAL" || busy} onClick={() => switchMode("live")} className="bg-rose-500 text-white hover:bg-rose-400 disabled:opacity-40">
                Activar modo REAL
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}
    </Panel>
  );
}
