import { useState } from "react";
import { Newspaper, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Panel } from "../Panel";
import { Field, INPUT, BTN } from "./SecuritySection";

const KEYS = ["news_enabled", "news_interval_min", "news_block_events", "news_event_before_min", "news_event_after_min", "news_block_critical", "news_reduce_on_high_risk", "news_size_factor"];
const Toggle = ({ label, hint, checked, onChange, testId }) => (
  <label className="flex cursor-pointer items-center justify-between gap-3 rounded-sm border border-[#1E293B] px-3 py-2">
    <span><span className="block text-[13px] text-slate-200">{label}</span><span className="block text-[11px] text-slate-500">{hint}</span></span>
    <Switch data-testid={testId} checked={checked} onCheckedChange={onChange} />
  </label>
);

export default function NewsSection({ config, onSave }) {
  const [form, setForm] = useState(Object.fromEntries(KEYS.map((k) => [k, config[k]])));
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const num = (k, v, min, max) => set(k, Math.min(max, Math.max(min, Number(v) || min)));

  const save = async () => {
    setBusy(true);
    await onSave({ ...form, news_size_factor: Number(form.news_size_factor) }, "Agente de noticias guardado");
    setBusy(false);
  };

  return (
    <Panel testId="news-section" title="Agente de noticias" icon={Newspaper} bodyClass="p-4 space-y-3"
      actions={<Button data-testid="news-save-button" size="sm" onClick={save} disabled={busy} className={`${BTN} h-7 text-[10px]`}><Save className="mr-1 h-3 w-3" /> Guardar</Button>}>
      <p className="text-[12px] leading-relaxed text-slate-400">
        Lee titulares de CoinDesk, CoinTelegraph, The Block y Decrypt más el calendario macro de EE. UU.; Claude los convierte en un nivel de riesgo y sentimiento por par.
        Ese contexto entra en la evaluación de cada señal y, si lo activas, pausa nuevas entradas alrededor de eventos de alto impacto o noticias críticas y reduce el tamaño cuando el riesgo es alto.
      </p>
      <Toggle label="Agente activo" hint="Analiza noticias de forma periódica (coste IA pequeño por ciclo)" checked={form.news_enabled} onChange={(v) => set("news_enabled", v)} testId="news-enabled-switch" />
      <Field label="Intervalo de análisis (min)">
        <Input data-testid="news-interval-input" type="number" min={5} max={240} value={form.news_interval_min} onChange={(e) => num("news_interval_min", e.target.value, 5, 240)} className={`${INPUT} num`} />
      </Field>
      <Toggle label="Pausar entradas en eventos macro de alto impacto" hint="FOMC, CPI, NFP… (impacto ALTO en el calendario USD)" checked={form.news_block_events} onChange={(v) => set("news_block_events", v)} testId="news-block-events-switch" />
      <div className="grid grid-cols-2 gap-3">
        <Field label="Minutos antes del evento">
          <Input data-testid="news-before-input" type="number" min={0} max={240} value={form.news_event_before_min} onChange={(e) => num("news_event_before_min", e.target.value, 0, 240)} className={`${INPUT} num`} />
        </Field>
        <Field label="Minutos después">
          <Input data-testid="news-after-input" type="number" min={0} max={240} value={form.news_event_after_min} onChange={(e) => num("news_event_after_min", e.target.value, 0, 240)} className={`${INPUT} num`} />
        </Field>
      </div>
      <Toggle label="Bloquear pares con noticia crítica" hint="Hack, insolvencia, delisting, sanción… durante 24 h" checked={form.news_block_critical} onChange={(v) => set("news_block_critical", v)} testId="news-block-critical-switch" />
      <Toggle label="Reducir tamaño con riesgo ALTO" hint="Aplica el factor de abajo al riesgo por operación" checked={form.news_reduce_on_high_risk} onChange={(v) => set("news_reduce_on_high_risk", v)} testId="news-reduce-switch" />
      <Field label="Factor de tamaño con riesgo alto (0.1 – 1.0)">
        <Input data-testid="news-size-factor-input" type="number" step={0.1} min={0.1} max={1} value={form.news_size_factor} onChange={(e) => set("news_size_factor", e.target.value)} className={`${INPUT} num`} />
      </Field>
    </Panel>
  );
}
