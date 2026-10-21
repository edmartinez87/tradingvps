import { useState } from "react";
import { CalendarClock, Loader2, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Panel } from "../Panel";
import { http, errMsg, fmtDateTime } from "@/lib/api";
import { Field, INPUT, BTN, BTN_OUT } from "./SecuritySection";

const DAYS = ["Domingo", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"];
const Toggle = ({ label, hint, checked, onChange, testId }) => (
  <label className="flex cursor-pointer items-center justify-between gap-3 rounded-sm border border-[#1E293B] px-3 py-2">
    <span><span className="block text-[13px] text-slate-200">{label}</span><span className="block text-[11px] text-slate-500">{hint}</span></span>
    <Switch data-testid={testId} checked={checked} onCheckedChange={onChange} />
  </label>
);

const DEFAULT_DESC = "Claude revisa rendimiento real, chequeo del plan y backtests, y ajusta el bot dentro de los topes de seguridad (riesgo ≤ 1.5%, apalancamiento ≤ 5x, mínimo 2 pares). Se dispara a las 08:00 UTC del día programado y te avisa por Telegram.";

export default function AutoReviewSection({ config, onSave, onRan, desc = DEFAULT_DESC }) {
  const [form, setForm] = useState({ auto_review_enabled: config.auto_review_enabled, auto_review_frequency: config.auto_review_frequency, auto_review_day: config.auto_review_day, auto_review_apply: config.auto_review_apply });
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState(null);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const save = async () => { setBusy("save"); await onSave(form, "Revisión automática guardada"); setBusy(""); };
  const runNow = async () => {
    setBusy("run");
    try {
      const { data } = await http.post("/ai/auto-review");
      setResult(data);
      toast.success(Object.keys(data.applied).length ? "Revisión ejecutada · cambios aplicados" : "Revisión ejecutada · sin cambios");
      onRan?.();
    } catch (e) {
      toast.error(errMsg(e));
    } finally {
      setBusy("");
    }
  };

  const changes = result ? Object.keys(result.applied) : Object.keys(config.auto_review_last_changes || {});
  const summary = result?.summary || config.auto_review_last_summary;
  return (
    <Panel testId="autoreview-section" title="Revisión IA automática" icon={CalendarClock} bodyClass="p-4 space-y-3">
      <p className="text-[12px] leading-relaxed text-slate-400">{desc}</p>
      <Toggle label="Revisión automática activa" hint="Programada por el sistema a las 08:00 UTC" checked={form.auto_review_enabled} onChange={(v) => set("auto_review_enabled", v)} testId="autoreview-enabled-switch" />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Frecuencia">
          <Select value={form.auto_review_frequency} onValueChange={(v) => set("auto_review_frequency", v)}>
            <SelectTrigger data-testid="autoreview-frequency-select" className={INPUT}><SelectValue /></SelectTrigger>
            <SelectContent className="border-[#1E293B] bg-[#0D111A]">
              <SelectItem value="weekly" className="font-mono text-xs">Semanal</SelectItem>
              <SelectItem value="daily" className="font-mono text-xs">Diaria</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        {form.auto_review_frequency === "weekly" && (
          <Field label="Día (UTC)">
            <Select value={String(form.auto_review_day)} onValueChange={(v) => set("auto_review_day", Number(v))}>
              <SelectTrigger data-testid="autoreview-day-select" className={INPUT}><SelectValue /></SelectTrigger>
              <SelectContent className="border-[#1E293B] bg-[#0D111A]">
                {DAYS.map((d, i) => <SelectItem key={d} value={String(i)} className="font-mono text-xs">{d}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
        )}
      </div>
      <Toggle label="Aplicar cambios automáticamente" hint="Desactivado: solo analiza y avisa por Telegram" checked={form.auto_review_apply} onChange={(v) => set("auto_review_apply", v)} testId="autoreview-apply-switch" />
      <div className="flex flex-wrap gap-2">
        <Button data-testid="autoreview-save-button" onClick={save} disabled={busy === "save"} className={BTN}>{busy === "save" && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />} Guardar</Button>
        <Button data-testid="autoreview-run-button" variant="outline" onClick={runNow} disabled={busy === "run"} className={`${BTN_OUT} border-purple-500/40 text-purple-200 hover:bg-purple-500/10`}>
          {busy === "run" ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Sparkles className="mr-1.5 h-3.5 w-3.5" />} {busy === "run" ? "Claude revisando..." : "Ejecutar ahora"}
        </Button>
      </div>
      {(summary || config.auto_review_last_at) && (
        <div data-testid="autoreview-last" className="rounded-sm border border-purple-500/30 bg-purple-500/5 p-3 text-[12px]">
          <p className="font-mono text-[10px] uppercase tracking-wider text-slate-500">Última revisión · {fmtDateTime(result?.ran_at || config.auto_review_last_at)} · {changes.length ? `${changes.length} cambio${changes.length > 1 ? "s" : ""}: ${changes.join(", ")}` : "sin cambios"}</p>
          <p data-testid="autoreview-last-summary" className="mt-1 leading-relaxed text-slate-200">{summary}</p>
        </div>
      )}
    </Panel>
  );
}
