import { useState } from "react";
import { Link2, Loader2, Plug, Trash2, ChevronDown } from "lucide-react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Panel } from "../Panel";
import { http, errMsg, fmtUsd, fmtDateTime } from "@/lib/api";
import { Field, INPUT, BTN, BTN_OUT } from "./SecuritySection";

const ENV_LABEL = { mainnet: "Mainnet · dinero real", testnet: "Testnet · fondos de prueba", demo: "Demo trading · cuenta demo de Bybit" };

export default function BybitSection({ config, onSave }) {
  const [form, setForm] = useState({ bybit_env: config.bybit_env, bybit_api_key: "", bybit_api_secret: "", bybit_base_url: config.bybit_base_url || "" });
  const [advanced, setAdvanced] = useState(!!config.bybit_base_url);
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const save = async () => {
    setBusy("save");
    const ok = await onSave(form, "Credenciales de Bybit guardadas · verifica la conexión");
    setBusy("");
    if (ok) setForm((f) => ({ ...f, bybit_api_key: "", bybit_api_secret: "" }));
  };
  const test = async () => {
    setBusy("test");
    setResult(null);
    try {
      const body = form.bybit_api_key && form.bybit_api_secret ? { api_key: form.bybit_api_key, api_secret: form.bybit_api_secret, env: form.bybit_env, base_url: form.bybit_base_url } : {};
      const { data } = await http.post("/bybit/test", body);
      setResult(data);
      toast.success(data.saved_credentials ? "Conexión con Bybit verificada" : "Conexión OK · guarda las credenciales para usarlas");
      if (data.saved_credentials) onSave({}, "Verificación registrada");
    } catch (e) {
      toast.error(errMsg(e));
    } finally {
      setBusy("");
    }
  };
  const clear = async () => { setBusy("clear"); await onSave({ clear_bybit: true }, "Credenciales de Bybit eliminadas"); setBusy(""); setResult(null); };

  return (
    <Panel testId="bybit-section" title="Bybit · cuenta real" icon={Link2} bodyClass="p-4 space-y-3"
      actions={config.bybit_configured && <span data-testid="bybit-configured-badge" className={`rounded-sm border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider ${config.bybit_verified_at ? "border-emerald-500/40 text-emerald-400" : "border-amber-500/40 text-amber-300"}`}>{config.bybit_verified_at ? "Verificada" : "Sin verificar"}</span>}>
      <p className="text-[12px] leading-relaxed text-slate-400">
        Crea la API key en Bybit → API Management → <span className="text-slate-200">System-generated · HMAC</span>, con permisos solo de <span className="text-slate-200">Contratos (Trade)</span> y lectura, <span className="text-rose-300">sin retiros</span>, restringida a la IP de tu VPS. La cuenta debe ser Unified (UTA) en modo unidireccional (One-Way).
        {config.secrets_encrypted ? " Las credenciales se guardan cifradas." : ""}
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Entorno">
          <Select value={form.bybit_env} onValueChange={(v) => setForm((f) => ({ ...f, bybit_env: v }))}>
            <SelectTrigger data-testid="bybit-env-select" className={INPUT}><SelectValue /></SelectTrigger>
            <SelectContent className="border-[#1E293B] bg-[#0D111A]">
              {config.bybit_envs.map((e) => <SelectItem key={e} value={e} className="font-mono text-xs">{ENV_LABEL[e] || e}</SelectItem>)}
            </SelectContent>
          </Select>
        </Field>
        <Field label={`API key${config.bybit_api_key ? ` · guardada ${config.bybit_api_key}` : ""}`}>
          <Input data-testid="bybit-api-key-input" autoComplete="off" value={form.bybit_api_key} placeholder={config.bybit_api_key || "API key"} onChange={set("bybit_api_key")} className={INPUT} />
        </Field>
      </div>
      <Field label={`API secret${config.bybit_api_secret ? ` · guardado ${config.bybit_api_secret}` : ""}`} hint="Déjalo vacío para mantener el guardado. Nunca se muestra completo.">
        <Input data-testid="bybit-api-secret-input" type="password" autoComplete="off" value={form.bybit_api_secret} placeholder={config.bybit_api_secret || "API secret"} onChange={set("bybit_api_secret")} className={INPUT} />
      </Field>
      <button type="button" data-testid="bybit-advanced-toggle" onClick={() => setAdvanced((a) => !a)} className="flex items-center gap-1 font-mono text-[10px] uppercase tracking-wider text-slate-500 hover:text-slate-300">
        <ChevronDown className={`h-3 w-3 transition-transform ${advanced ? "rotate-180" : ""}`} /> Avanzado · endpoint personalizado
      </button>
      {advanced && (
        <Field label="Endpoint (opcional)" hint="Vacío = URL oficial del entorno. Útil para dominios alternativos de Bybit (p. ej. api.bytick.com).">
          <Input data-testid="bybit-base-url-input" value={form.bybit_base_url} placeholder="https://api.bybit.com" onChange={set("bybit_base_url")} className={INPUT} />
        </Field>
      )}
      <div className="flex flex-wrap gap-2">
        <Button data-testid="bybit-save-button" onClick={save} disabled={busy === "save"} className={BTN}>{busy === "save" && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />} Guardar</Button>
        <Button data-testid="bybit-test-button" variant="outline" onClick={test} disabled={busy === "test" || (!config.bybit_configured && !(form.bybit_api_key && form.bybit_api_secret))} className={BTN_OUT}>
          {busy === "test" ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Plug className="mr-1.5 h-3.5 w-3.5" />} Probar conexión
        </Button>
        {config.bybit_configured && (
          <Button data-testid="bybit-clear-button" variant="ghost" onClick={clear} disabled={busy === "clear"} className="h-9 font-mono text-[11px] uppercase tracking-wider text-slate-400 hover:text-rose-300"><Trash2 className="mr-1.5 h-3.5 w-3.5" /> Quitar</Button>
        )}
      </div>
      {config.bybit_verified_at && !result && (
        <p className="font-mono text-[10px] uppercase tracking-wider text-slate-500">Última verificación {fmtDateTime(config.bybit_verified_at)} · equidad {fmtUsd(config.bybit_verified_equity || 0)}</p>
      )}
      {result && (
        <div data-testid="bybit-test-result" className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-emerald-500/30 bg-[#1E293B] sm:grid-cols-4">
          {[["Entorno", result.env], ["Equidad", fmtUsd(result.wallet.equity)], ["Disponible", fmtUsd(result.wallet.available)], ["Posiciones abiertas", result.open_positions],
            ["Cuenta", result.wallet.account_type], ["Desfase reloj", `${result.server_offset_ms ?? "—"} ms`], ["PnL no realizado", fmtUsd(result.wallet.unrealised)], ["Endpoint", result.base_url.replace("https://", "")]].map(([l, v]) => (
            <div key={l} className="bg-[#0D111A] px-3 py-2"><p className="font-mono text-[9px] uppercase tracking-[0.16em] text-slate-500">{l}</p><p className="num mt-0.5 truncate text-[12px] font-semibold text-slate-100">{v}</p></div>
          ))}
        </div>
      )}
    </Panel>
  );
}
