import { useState } from "react";
import { BrainCircuit, Loader2, Plug } from "lucide-react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Panel } from "../Panel";
import { http, errMsg } from "@/lib/api";
import { Field, INPUT, BTN, BTN_OUT } from "./SecuritySection";

const PROVIDER_LABEL = { anthropic: "Anthropic (Claude)", openai: "OpenAI (GPT)", gemini: "Google (Gemini)" };

export default function AiSection({ config, onSave }) {
  const [form, setForm] = useState({ ai_provider: config.ai_provider, ai_model: config.ai_model, ai_api_key: "" });
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [reply, setReply] = useState(null);

  const save = async (extra = {}) => {
    setSaving(true);
    const ok = await onSave({ ...form, ...extra }, "Configuración de IA guardada");
    setSaving(false);
    if (ok) setForm((f) => ({ ...f, ai_api_key: "" }));
  };
  const test = async () => {
    setTesting(true);
    setReply(null);
    try {
      const { data } = await http.post("/ai/test");
      setReply(`${data.provider}/${data.model}: ${data.reply}`);
      toast.success("La IA respondió correctamente");
    } catch (e) {
      setReply(null);
      toast.error(errMsg(e));
    } finally {
      setTesting(false);
    }
  };

  return (
    <Panel testId="ai-section" title="Inteligencia artificial" icon={BrainCircuit} bodyClass="p-4 space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Proveedor">
          <Select value={form.ai_provider} onValueChange={(v) => setForm((f) => ({ ...f, ai_provider: v }))}>
            <SelectTrigger data-testid="ai-provider-select" className={INPUT}><SelectValue /></SelectTrigger>
            <SelectContent className="border-[#1E293B] bg-[#0D111A]">
              {config.ai_providers.map((p) => <SelectItem key={p} value={p} className="font-mono text-xs">{PROVIDER_LABEL[p] || p}</SelectItem>)}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Modelo" hint="Ej.: claude-sonnet-5-5, claude-haiku-4-5, gpt-5.5, gemini-3-flash">
          <Input data-testid="ai-model-input" value={form.ai_model} onChange={(e) => setForm((f) => ({ ...f, ai_model: e.target.value }))} className={INPUT} />
        </Field>
      </div>
      <Field label={`API key · actual: ${config.ai_key_source === "custom" ? `propia ${config.ai_api_key}` : "clave universal de Emergent"}`}
        hint="Déjala vacía para mantener la actual. La clave universal de Emergent funciona con Claude, GPT y Gemini sin configurar nada.">
        <Input data-testid="ai-api-key-input" type="password" autoComplete="off" value={form.ai_api_key} placeholder={config.ai_key_source === "custom" ? config.ai_api_key : "sk-… (opcional)"}
          onChange={(e) => setForm((f) => ({ ...f, ai_api_key: e.target.value }))} className={INPUT} />
      </Field>
      <div className="flex flex-wrap gap-2">
        <Button data-testid="ai-save-button" onClick={() => save()} disabled={saving} className={BTN}>{saving && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />} Guardar</Button>
        {config.ai_key_source === "custom" && (
          <Button data-testid="ai-clear-key-button" variant="outline" onClick={() => save({ clear_ai_api_key: true })} className={BTN_OUT}>Volver a la clave de Emergent</Button>
        )}
        <Button data-testid="ai-test-button" variant="outline" onClick={test} disabled={testing} className={BTN_OUT}>
          {testing ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Plug className="mr-1.5 h-3.5 w-3.5" />} Probar conexión
        </Button>
      </div>
      {reply && <p data-testid="ai-test-reply" className="rounded-sm border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-[12px] text-emerald-200">{reply}</p>}
    </Panel>
  );
}
