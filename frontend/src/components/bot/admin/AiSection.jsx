import { useEffect, useState } from "react";
import { BrainCircuit, Loader2, Plug, KeyRound, Sparkles, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Panel } from "../Panel";
import { http, errMsg } from "@/lib/api";
import { Field, INPUT, BTN, BTN_OUT } from "./SecuritySection";
import { ModelPicker } from "./ModelPicker";

const PROVIDER_LABEL = { anthropic: "Anthropic (Claude)", openai: "OpenAI (GPT)", gemini: "Google (Gemini)" };
const SOURCES = [
  { id: "emergent", icon: Sparkles, title: "Clave universal de Emergent", desc: "Sin configurar nada: Claude, GPT o Gemini con el saldo de tu clave Emergent." },
  { id: "gemini", icon: KeyRound, title: "Google Gemini · mi API key", desc: "Usa tu propia clave de Google AI Studio; el consumo se factura en tu cuenta de Google." },
];

const SourceCard = ({ s, active, onClick }) => (
  <button type="button" data-testid={`ai-source-${s.id}`} onClick={onClick} aria-pressed={active}
    className={`rounded-sm border px-3 py-2.5 text-left transition-colors ${active ? "border-amber-500/60 bg-amber-500/10" : "border-[#1E293B] bg-[#07090E] hover:border-slate-600"}`}>
    <span className={`flex items-center gap-2 text-[13px] font-semibold ${active ? "text-amber-200" : "text-slate-200"}`}><s.icon className="h-3.5 w-3.5" /> {s.title}</span>
    <span className="mt-1 block text-[11px] leading-snug text-slate-500">{s.desc}</span>
  </button>
);

const fromConfig = (c) => ({ ai_source: c.ai_source, ai_provider: c.ai_provider, ai_model: c.ai_model, gemini_model: c.gemini_model, gemini_api_key: "" });

export default function AiSection({ config, onSave }) {
  const [form, setForm] = useState(fromConfig(config));
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState("");
  const [reply, setReply] = useState(null);
  const set = (k, v) => { setDirty(true); setForm((f) => ({ ...f, [k]: v })); };
  const gemini = form.ai_source === "gemini";
  const active = config.ai_active;
  // Keep the form in sync with the saved config (other bot / tab / background job) while the user has no unsaved edits.
  useEffect(() => { if (!dirty) setForm(fromConfig(config)); }, [dirty, config.ai_source, config.ai_provider, config.ai_model, config.gemini_model]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async (extra = {}) => {
    setBusy("save");
    const ok = await onSave({ ...form, ...extra }, "Configuración de IA guardada");
    setBusy("");
    if (ok) setDirty(false);
  };
  const test = async () => {
    setBusy("test");
    setReply(null);
    try {
      const { data } = await http.post("/ai/test", form);
      setReply(`${data.label} (${data.source === "gemini" ? "tu clave de Google" : "clave Emergent"}): ${data.reply}`);
      toast.success("La IA respondió correctamente · recuerda guardar para activarla");
    } catch (e) {
      toast.error(errMsg(e));
    } finally {
      setBusy("");
    }
  };

  return (
    <Panel testId="ai-section" title="Inteligencia artificial" icon={BrainCircuit} bodyClass="p-4 space-y-3">
      <p data-testid="ai-active-label" className={`rounded-sm border px-3 py-2 text-[12px] ${active.health?.ok === false ? "border-rose-500/50 bg-rose-500/10 text-rose-200" : "border-[#1E293B] bg-[#07090E] text-slate-300"}`}>
        Activa ahora en ambos bots: <span className={`font-semibold ${active.health?.ok === false ? "text-rose-300" : "text-amber-300"}`}>{active.label}</span> <span className={active.health?.ok === false ? "text-rose-300/70" : "text-slate-500"}>· {active.source === "gemini" ? "tu API key de Google Gemini" : "clave universal de Emergent"} · {active.model}</span>
        {active.health?.ok === false && <span data-testid="ai-health-error" className="mt-1 block font-mono text-[11px] text-rose-300">⚠ Sin servicio · {active.health.label}: {active.health.error}</span>}
      </p>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {SOURCES.map((s) => <SourceCard key={s.id} s={s} active={form.ai_source === s.id} onClick={() => set("ai_source", s.id)} />)}
      </div>
      {gemini ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label={`API key de Google Gemini${config.gemini_configured ? ` · guardada ${config.gemini_api_key}` : ""}`}
            hint={<>Déjala vacía para mantener la guardada. <a data-testid="gemini-key-link" href={config.gemini_key_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sky-300 hover:underline">Obtener una API key en Google AI Studio <ExternalLink className="h-3 w-3" /></a></>}>
            <Input data-testid="gemini-api-key-input" type="password" autoComplete="off" value={form.gemini_api_key} placeholder={config.gemini_configured ? config.gemini_api_key : "AIza…"}
              onChange={(e) => set("gemini_api_key", e.target.value)} className={INPUT} />
          </Field>
          <Field label="Modelo de Gemini" hint="Pro = más razonamiento; Flash = más rápido y barato.">
            <ModelPicker models={config.gemini_models} value={form.gemini_model} onChange={(v) => set("gemini_model", v)} testId="gemini-model" />
          </Field>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Proveedor">
            <Select value={form.ai_provider} onValueChange={(v) => { setDirty(true); setForm((f) => ({ ...f, ai_provider: v, ai_model: config.ai_models[v]?.[0] || f.ai_model })); }}>
              <SelectTrigger data-testid="ai-provider-select" className={INPUT}><SelectValue /></SelectTrigger>
              <SelectContent className="border-[#1E293B] bg-[#0D111A]">
                {config.ai_providers.map((p) => <SelectItem key={p} value={p} className="font-mono text-xs">{PROVIDER_LABEL[p] || p}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Modelo" hint="El consumo se descuenta del saldo de tu clave Emergent.">
            <ModelPicker models={config.ai_models[form.ai_provider] || []} value={form.ai_model} onChange={(v) => set("ai_model", v)} testId="ai-model" />
          </Field>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button data-testid="ai-save-button" onClick={() => save()} disabled={!!busy} className={BTN}>{busy === "save" && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />} Guardar</Button>
        <Button data-testid="ai-test-button" variant="outline" onClick={test} disabled={!!busy} className={BTN_OUT}>
          {busy === "test" ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Plug className="mr-1.5 h-3.5 w-3.5" />} Probar conexión
        </Button>
        {config.gemini_configured && (
          <Button data-testid="ai-clear-gemini-button" variant="outline" onClick={() => save({ clear_gemini_api_key: true })} disabled={!!busy} className={`${BTN_OUT} text-rose-300 hover:bg-rose-500/10`}>Quitar clave de Gemini</Button>
        )}
      </div>
      {reply && <p data-testid="ai-test-reply" className="rounded-sm border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-[12px] text-emerald-200">{reply}</p>}
    </Panel>
  );
}
