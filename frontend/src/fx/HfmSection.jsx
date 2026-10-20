import { useState } from "react";
import { Landmark, Loader2, Plug, Trash2, Link2 } from "lucide-react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Panel } from "@/components/bot/Panel";
import { http, errMsg, fmtDateTime } from "@/lib/api";
import { Field, INPUT, BTN, BTN_OUT } from "@/components/bot/admin/SecuritySection";

const STATE_TONE = { DEPLOYED: "border-emerald-500/40 text-emerald-400", TOKEN_OK: "border-sky-500/40 text-sky-300" };
const Sel = ({ value, onChange, options, testId, render }) => (
  <Select value={value} onValueChange={onChange}>
    <SelectTrigger data-testid={testId} className={INPUT}><SelectValue /></SelectTrigger>
    <SelectContent className="border-[#1E293B] bg-[#0D111A]">
      {options.map((o) => <SelectItem key={o} value={o} className="font-mono text-xs">{render ? render(o) : o}</SelectItem>)}
    </SelectContent>
  </Select>
);

export default function HfmSection({ config, onSave, onRefresh }) {
  const [form, setForm] = useState({ metaapi_token: "", mt_login: config.mt_login || "", mt_password: "", mt_server: config.mt_server || "",
    mt_platform: config.mt_platform || "mt5", metaapi_region: config.metaapi_region || "new-york" });
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const save = async () => {
    setBusy("save");
    const body = Object.fromEntries(Object.entries(form).filter(([k, v]) => v !== "" || !["metaapi_token", "mt_password"].includes(k)));
    const ok = await onSave(body, "Datos de HFM guardados · prueba la conexión");
    setBusy("");
    if (ok) setForm((f) => ({ ...f, metaapi_token: "", mt_password: "" }));
  };
  const test = async () => {
    setBusy("test");
    setResult(null);
    try {
      const body = form.metaapi_token ? { ...form } : {};
      const { data } = await http.post("/hfm/test", body);
      setResult(data);
      toast.success(data.info ? "Cuenta HFM conectada vía MetaApi" : data.hint || "Token válido");
      onRefresh?.();
    } catch (e) {
      toast.error(errMsg(e));
    } finally {
      setBusy("");
    }
  };
  const link = async () => {
    setBusy("link");
    try {
      const { data } = await http.post("/hfm/link");
      setResult((r) => ({ ...(r || {}), account: data.account, hint: data.hint }));
      toast.success("Cuenta vinculada en MetaApi · desplegando");
      onRefresh?.();
    } catch (e) {
      toast.error(errMsg(e));
    } finally {
      setBusy("");
    }
  };
  const clear = async () => { setBusy("clear"); await onSave({ clear_hfm: true }, "Datos de HFM eliminados"); setBusy(""); setResult(null); };
  const acc = result?.account;

  return (
    <Panel testId="hfm-section" title="HotForex (HFM) · cuenta real vía MetaApi" icon={Landmark} bodyClass="p-4 space-y-3"
      actions={config.hfm_configured && (
        <span data-testid="hfm-state-badge" className={`rounded-sm border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider ${config.hfm_verified_at ? STATE_TONE.DEPLOYED : STATE_TONE[config.hfm_state] || "border-amber-500/40 text-amber-300"}`}>
          {config.hfm_verified_at ? "Verificada" : config.hfm_state || "Sin verificar"}
        </span>
      )}>
      <p className="text-[12px] leading-relaxed text-slate-400">
        HFM opera con MetaTrader 4/5 y no tiene API REST, así que el puente es <span className="text-slate-200">MetaApi.cloud</span> (plan gratuito para 1 cuenta). Pasos: 1) crea una cuenta en metaapi.cloud y copia el token (app.metaapi.cloud/token);
        2) introduce el login MT, la contraseña (<span className="text-slate-200">investor</span> para solo lectura, master para operar) y el servidor exacto de HFM (p.ej. <span className="num text-slate-200">HFMarketsGlobal-Live2</span>);
        3) guarda, <span className="text-slate-200">Vincular cuenta</span> y luego <span className="text-slate-200">Probar conexión</span>. Mientras tanto el bot opera en paper con precios de Yahoo Finance.
        {config.secrets_encrypted ? " Token y contraseña se guardan cifrados." : ""}
      </p>
      <Field label={`Token de MetaApi${config.metaapi_token ? ` · guardado ${config.metaapi_token}` : ""}`}>
        <Input data-testid="hfm-token-input" type="password" autoComplete="off" value={form.metaapi_token} placeholder={config.metaapi_token || "eyJhbGciOi…"} onChange={set("metaapi_token")} className={INPUT} />
      </Field>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Login MetaTrader (número de cuenta HFM)">
          <Input data-testid="hfm-login-input" autoComplete="off" value={form.mt_login} placeholder="12345678" onChange={set("mt_login")} className={`${INPUT} num`} />
        </Field>
        <Field label={`Contraseña MT${config.mt_password ? " · guardada" : ""}`}>
          <Input data-testid="hfm-password-input" type="password" autoComplete="new-password" value={form.mt_password} placeholder={config.mt_password ? "••••••••" : "Contraseña investor o master"} onChange={set("mt_password")} className={INPUT} />
        </Field>
        <Field label="Servidor HFM" hint="Exactamente como aparece en MetaTrader (Live/Demo)">
          <Input data-testid="hfm-server-input" autoComplete="off" value={form.mt_server} placeholder="HFMarketsGlobal-Live2" onChange={set("mt_server")} className={INPUT} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Plataforma"><Sel value={form.mt_platform} onChange={(v) => setForm((f) => ({ ...f, mt_platform: v }))} options={config.mt_platforms || ["mt5", "mt4"]} testId="hfm-platform-select" render={(o) => o.toUpperCase()} /></Field>
          <Field label="Región MetaApi"><Sel value={form.metaapi_region} onChange={(v) => setForm((f) => ({ ...f, metaapi_region: v }))} options={config.metaapi_regions || ["new-york", "london"]} testId="hfm-region-select" /></Field>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button data-testid="hfm-save-button" onClick={save} disabled={busy === "save"} className={BTN}>{busy === "save" && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />} Guardar</Button>
        <Button data-testid="hfm-link-button" variant="outline" onClick={link} disabled={busy === "link" || !config.hfm_configured} className={BTN_OUT} title={config.hfm_configured ? "Crea y despliega la cuenta en MetaApi" : "Guarda primero token, login, contraseña y servidor"}>
          {busy === "link" ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Link2 className="mr-1.5 h-3.5 w-3.5" />} Vincular cuenta
        </Button>
        <Button data-testid="hfm-test-button" variant="outline" onClick={test} disabled={busy === "test" || !(form.metaapi_token || config.metaapi_token)} className={BTN_OUT}>
          {busy === "test" ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Plug className="mr-1.5 h-3.5 w-3.5" />} Probar conexión
        </Button>
        {config.hfm_configured && (
          <Button data-testid="hfm-clear-button" variant="ghost" onClick={clear} disabled={busy === "clear"} className="h-9 font-mono text-[11px] uppercase tracking-wider text-rose-300 hover:bg-rose-500/10">
            <Trash2 className="mr-1.5 h-3.5 w-3.5" /> Quitar
          </Button>
        )}
      </div>
      {(result || config.hfm_verified_at) && (
        <div data-testid="hfm-test-result" className="space-y-1.5 rounded-sm border border-[#1E293B] bg-[#0B1220] p-3 font-mono text-[11px] text-slate-300">
          {result?.token_valid && <p>Token MetaApi: <span className="text-emerald-400">válido</span> · {result.accounts_total} cuenta(s) en MetaApi</p>}
          {acc && <p>Cuenta {acc.login} · {acc.server} · estado <span className={acc.state === "DEPLOYED" ? "text-emerald-400" : "text-amber-300"}>{acc.state}</span> · conexión {acc.connection || "—"} · región {acc.region}</p>}
          {result?.info && (
            <p>Bróker {result.info.broker} · {result.info.currency} · balance <span className="num text-slate-100">{result.info.balance}</span> · equidad <span className="num text-slate-100">{result.info.equity}</span> · margen libre {result.info.freeMargin} · apalancamiento 1:{result.info.leverage} · {result.positions?.length || 0} posiciones abiertas</p>
          )}
          {result?.hint && <p className="text-amber-300">{result.hint}</p>}
          {!result && config.hfm_verified_at && <p>Última verificación {fmtDateTime(config.hfm_verified_at)} · equidad {config.hfm_verified_equity} {config.hfm_currency} · apalancamiento 1:{config.hfm_leverage}</p>}
        </div>
      )}
      <p className="text-[11px] text-slate-500">La ejecución REAL en HFM (órdenes vía MetaApi) llegará en la siguiente fase; estos datos quedan guardados y verificados para activarla.</p>
    </Panel>
  );
}
