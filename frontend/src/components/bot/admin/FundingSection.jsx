import { useState } from "react";
import { Percent, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Panel } from "../Panel";
import { Field, INPUT, BTN } from "./SecuritySection";

const KEYS = ["funding_enabled", "funding_block_pct", "funding_reduce_pct", "funding_reduce", "funding_size_factor"];
const Toggle = ({ label, hint, checked, onChange, testId }) => (
  <label className="flex cursor-pointer items-center justify-between gap-3 rounded-sm border border-[#1E293B] px-3 py-2">
    <span><span className="block text-[13px] text-slate-200">{label}</span><span className="block text-[11px] text-slate-500">{hint}</span></span>
    <Switch data-testid={testId} checked={checked} onCheckedChange={onChange} />
  </label>
);

export default function FundingSection({ config, onSave }) {
  const [form, setForm] = useState(Object.fromEntries(KEYS.map((k) => [k, config[k]])));
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const save = async () => {
    setBusy(true);
    await onSave({ ...form, funding_block_pct: Number(form.funding_block_pct), funding_reduce_pct: Number(form.funding_reduce_pct), funding_size_factor: Number(form.funding_size_factor) }, "Filtro de funding guardado");
    setBusy(false);
  };

  return (
    <Panel testId="funding-section" title="Filtro de funding" icon={Percent} bodyClass="p-4 space-y-3"
      actions={<Button data-testid="funding-save-button" size="sm" onClick={save} disabled={busy} className={`${BTN} h-7 text-[10px]`}><Save className="mr-1 h-3 w-3" /> Guardar</Button>}>
      <p className="text-[12px] leading-relaxed text-slate-400">
        El funding es lo que pagan los largos a los cortos (si es positivo) o al revés en cada liquidación: cada 8 h en la mayoría de pares, cada 4 h o 1 h en algunos.
        Un funding muy alto significa un lado sobrecargado y una posición que paga por mantenerse:
        abrir <span className="text-slate-200">en contra</span> (long con funding muy positivo, short con funding muy negativo) es caro y propenso a liquidaciones en cadena.
        La IA recibe el funding interpretado en cada señal; con estos umbrales el bot además bloquea o reduce la entrada. Lo normal es ±0.01 % por 8 h.
      </p>
      <p data-testid="funding-interval-note" className="rounded-sm border border-[#1E293B] bg-[#0B1220] px-3 py-2 text-[11px] leading-relaxed text-slate-500">
        Los umbrales se expresan <span className="text-slate-300">por 8 h</span>. El bot lee el intervalo real de cada par y lo normaliza: un 0.05 % cada 4 h cuenta como 0.10 % por 8 h.
        En el mercado en vivo el chip muestra <span className="num text-slate-300">/4h</span> o <span className="num text-slate-300">/1h</span> cuando el par no liquida cada 8 h.
      </p>
      <Toggle label="Filtro activo" hint="Bloquea y reduce según los umbrales de abajo (la IA lo tiene en cuenta siempre)" checked={form.funding_enabled} onChange={(v) => set("funding_enabled", v)} testId="funding-enabled-switch" />
      <div className="grid grid-cols-2 gap-3">
        <Field label="Bloquear si funding en contra ≥ (% por 8 h)" hint="0.10 % = 10× lo normal">
          <Input data-testid="funding-block-input" type="number" step={0.01} min={0.01} max={2} value={form.funding_block_pct} onChange={(e) => set("funding_block_pct", e.target.value)} className={`${INPUT} num`} />
        </Field>
        <Field label="Reducir tamaño si ≥ (% por 8 h)" hint="Debe ser menor que el de bloqueo">
          <Input data-testid="funding-reduce-input" type="number" step={0.01} min={0} max={2} value={form.funding_reduce_pct} onChange={(e) => set("funding_reduce_pct", e.target.value)} className={`${INPUT} num`} />
        </Field>
      </div>
      <Toggle label="Reducir tamaño con funding ALTO en contra" hint="Aplica el factor de abajo al riesgo por operación" checked={form.funding_reduce} onChange={(v) => set("funding_reduce", v)} testId="funding-reduce-switch" />
      <Field label="Factor de tamaño (0.1 – 1.0)">
        <Input data-testid="funding-size-factor-input" type="number" step={0.1} min={0.1} max={1} value={form.funding_size_factor} onChange={(e) => set("funding_size_factor", e.target.value)} className={`${INPUT} num`} />
      </Field>
    </Panel>
  );
}
