import { useState } from "react";
import { Landmark, Loader2, Plug, Trash2, Link2, RefreshCw, ListChecks, ChevronDown } from "lucide-react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Panel } from "@/components/bot/Panel";
import { http, errMsg, fmtDateTime } from "@/lib/api";
import { Field, INPUT, BTN, BTN_OUT } from "@/components/bot/admin/SecuritySection";

const STATE_TONE = { DEPLOYED: "border-emerald-500/40 text-emerald-400", TOKEN_OK: "border-sky-500/40 text-sky-300" };
const REDEPLOY_STATES = ["DEPLOY_FAILED", "REDEPLOY_FAILED", "UNDEPLOYED", "DISCONNECTED", "DISCONNECTED_FROM_BROKER"];
const Sel = ({ value, onChange, options, testId, render }) => (
  <Select value={value} onValueChange={onChange}>
    <SelectTrigger data-testid={testId} className={INPUT}><SelectValue /></SelectTrigger>
    <SelectContent className="border-[#1E293B] bg-[#0D111A]">
      {options.map((o) => <SelectItem key={o} value={o} className="font-mono text-xs">{render ? render(o) : o}</SelectItem>)}
    </SelectContent>
  </Select>
);

function SymbolsCheck({ data }) {
  const rows = Object.entries(data.symbols);
  return (
    <div data-testid="hfm-symbols-result" className="rounded-sm border border-[#1E293B] bg-[#0B1220] p-3 font-mono text-[11px] text-slate-300">
      <p className={data.missing.length ? "text-amber-300" : "text-emerald-400"}>
        {data.missing.length ? `${data.missing.length} par(es) sin cotización en HFM: ${data.missing.join(", ")} · revisa el sufijo de símbolos` : `Los ${rows.length} pares activos cotizan en HFM${data.suffix ? ` con sufijo «${data.suffix}»` : ""}`}
      </p>
      <div className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-0.5 sm:grid-cols-3">
        {rows.map(([sym, r]) => (
          <span key={sym} data-testid={`hfm-symbol-${sym}`} className={r.ok ? "text-slate-300" : "text-rose-300"}>
            {r.broker_symbol}{r.ok ? ` · ${r.bid} / ${r.ask} · mín ${r.min_lot}` : ` · ${r.error}`}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function HfmSection({ config, onSave, onRefresh }) {
  const [form, setForm] = useState({ metaapi_token: "", mt_login: config.mt_login || "", mt_password: "", mt_server: config.mt_server || "",
    mt_platform: config.mt_platform || "mt5", metaapi_region: config.metaapi_region || "new-york", mt_symbol_suffix: config.mt_symbol_suffix || "",
    metaapi_base_url: config.metaapi_base_url || "", hfm_alert_after_sec: config.hfm_alert_after_sec ?? 60 });
  const [advanced, setAdvanced] = useState(!!config.metaapi_base_url);
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState(null);
  const [symbols, setSymbols] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const run = async (key, fn) => {
    setBusy(key);
    try { await fn(); } catch (e) { toast.error(errMsg(e)); } finally { setBusy(""); }
  };

  const save = async () => {
    setBusy("save");
    const body = Object.fromEntries(Object.entries(form).filter(([k, v]) => v !== "" || !["metaapi_token", "mt_password"].includes(k)));
    body.hfm_alert_after_sec = Math.min(3600, Math.max(10, Number(form.hfm_alert_after_sec) || 60));
    const ok = await onSave(body, "Datos de HFM guardados · vincula y prueba la conexión");
    setBusy("");
    if (ok) setForm((f) => ({ ...f, metaapi_token: "", mt_password: "", hfm_alert_after_sec: body.hfm_alert_after_sec }));
  };
  const test = () => run("test", async () => {
    setResult(null);
    const { data } = await http.post("/hfm/test", form.metaapi_token ? { ...form } : {});
    setResult(data);
    toast[data.info && data.info.tradeAllowed === false ? "warning" : "success"](data.info ? (data.info.tradeAllowed === false ? "Conectada, pero sin permiso de trading" : "Cuenta HFM conectada vía MetaApi") : data.hint || "Token válido");
    onRefresh?.();
  });
  const link = () => run("link", async () => {
    const { data } = await http.post("/hfm/link");
    setResult((r) => ({ ...(r || {}), account: data.account, hint: data.hint }));
    toast.success("Cuenta vinculada en MetaApi · desplegando");
    onRefresh?.();
  });
  const redeploy = () => run("redeploy", async () => {
    const { data } = await http.post("/hfm/redeploy");
    setResult((r) => ({ ...(r || {}), account: data.account, hint: data.hint }));
    toast.success("Redespliegue solicitado");
    onRefresh?.();
  });
  const checkSymbols = () => run("symbols", async () => {
    const { data } = await http.post("/hfm/symbols");
    setSymbols(data);
    toast[data.missing.length ? "warning" : "success"](data.missing.length ? `${data.missing.length} par(es) sin cotización en HFM` : "Todos los pares cotizan en HFM");
  });
  const clear = async () => {
    setBusy("clear");
    const ok = await onSave({ clear_hfm: true }, "Datos de HFM eliminados");
    setBusy(""); setResult(null); setSymbols(null);
    if (ok) setForm({ metaapi_token: "", mt_login: "", mt_password: "", mt_server: "", mt_platform: "mt5", metaapi_region: "new-york", mt_symbol_suffix: "", metaapi_base_url: "", hfm_alert_after_sec: config.hfm_alert_after_sec ?? 60 });
  };
  const acc = result?.account;
  const linked = !!config.metaapi_account_id;
  const canRedeploy = linked && (REDEPLOY_STATES.includes(config.hfm_state) || REDEPLOY_STATES.includes(config.hfm_connection) || acc?.state === "DEPLOY_FAILED");

  return (
    <Panel testId="hfm-section" title="HotForex (HFM) · cuenta real vía MetaApi" icon={Landmark} bodyClass="p-4 space-y-3"
      actions={config.hfm_configured && (
        <span data-testid="hfm-state-badge" className={`rounded-sm border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider ${config.hfm_verified_at ? STATE_TONE.DEPLOYED : STATE_TONE[config.hfm_state] || "border-amber-500/40 text-amber-300"}`}>
          {config.hfm_verified_at ? (config.hfm_trade_allowed === false ? "Solo lectura" : "Verificada") : config.hfm_state || "Sin verificar"}
        </span>
      )}>
      <p className="text-[12px] leading-relaxed text-slate-400">
        HFM opera con MetaTrader 4/5 y no tiene API REST, así que el puente es <span className="text-slate-200">MetaApi.cloud</span> (plan gratuito para 1 cuenta). Pasos: 1) crea una cuenta en metaapi.cloud y copia el token (app.metaapi.cloud/token);
        2) introduce el login MT, la contraseña <span className="text-slate-200">master</span> (la investor solo permite leer) y el servidor exacto de HFM (p.ej. <span className="num text-slate-200">HFMarketsGlobal-Live2</span>);
        3) guarda, <span className="text-slate-200">Vincular cuenta</span>, <span className="text-slate-200">Probar conexión</span> y <span className="text-slate-200">Comprobar símbolos</span>. Después activa el modo REAL en la tarjeta «Modo de operación». Empieza con una cuenta demo de HFM.
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
          <Input data-testid="hfm-password-input" type="password" autoComplete="new-password" value={form.mt_password} placeholder={config.mt_password ? "••••••••" : "Contraseña master"} onChange={set("mt_password")} className={INPUT} />
        </Field>
        <Field label="Servidor HFM" hint="Exactamente como aparece en MetaTrader (Live/Demo)">
          <Input data-testid="hfm-server-input" autoComplete="off" value={form.mt_server} placeholder="HFMarketsGlobal-Live2" onChange={set("mt_server")} className={INPUT} />
        </Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Plataforma"><Sel value={form.mt_platform} onChange={(v) => setForm((f) => ({ ...f, mt_platform: v }))} options={config.mt_platforms || ["mt5", "mt4"]} testId="hfm-platform-select" render={(o) => o.toUpperCase()} /></Field>
          <Field label="Región"><Sel value={form.metaapi_region} onChange={(v) => setForm((f) => ({ ...f, metaapi_region: v }))} options={config.metaapi_regions || ["new-york", "london"]} testId="hfm-region-select" /></Field>
          <Field label="Sufijo símbolos" hint="p.ej. «.r» si HFM muestra EURUSD.r">
            <Input data-testid="hfm-suffix-input" autoComplete="off" value={form.mt_symbol_suffix} placeholder="(ninguno)" onChange={set("mt_symbol_suffix")} className={INPUT} />
          </Field>
        </div>
      </div>
      <button data-testid="hfm-advanced-toggle" onClick={() => setAdvanced((v) => !v)} className="flex items-center gap-1 font-mono text-[10px] uppercase tracking-wider text-slate-500 hover:text-slate-300">
        <ChevronDown className={`h-3 w-3 transition-transform ${advanced ? "rotate-180" : ""}`} /> Avanzado · endpoint de MetaApi y aviso de desconexión
      </button>
      {advanced && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Endpoint personalizado (vacío = MetaApi.cloud)" hint="Solo para pruebas con un servidor MetaApi propio o un mock local">
            <Input data-testid="hfm-base-url-input" autoComplete="off" value={form.metaapi_base_url} placeholder="https://…" onChange={set("metaapi_base_url")} className={INPUT} />
          </Field>
          <Field label="Aviso de desconexión (segundos)" hint="En modo REAL, si la cuenta HFM pierde la conexión con MetaApi durante más de este tiempo, recibirás un aviso por Telegram (y otro al restablecerse). 10–3600 s.">
            <Input data-testid="hfm-alert-after-input" type="number" min={10} max={3600} step={5} value={form.hfm_alert_after_sec} onChange={set("hfm_alert_after_sec")} className={`${INPUT} num`} />
          </Field>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button data-testid="hfm-save-button" onClick={save} disabled={busy === "save"} className={BTN}>{busy === "save" && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />} Guardar</Button>
        <Button data-testid="hfm-link-button" variant="outline" onClick={link} disabled={busy === "link" || !config.hfm_configured} className={BTN_OUT} title={config.hfm_configured ? "Crea y despliega la cuenta en MetaApi" : "Guarda primero token, login, contraseña y servidor"}>
          {busy === "link" ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Link2 className="mr-1.5 h-3.5 w-3.5" />} Vincular cuenta
        </Button>
        <Button data-testid="hfm-test-button" variant="outline" onClick={test} disabled={busy === "test" || !(form.metaapi_token || config.metaapi_token)} className={BTN_OUT}>
          {busy === "test" ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Plug className="mr-1.5 h-3.5 w-3.5" />} Probar conexión
        </Button>
        <Button data-testid="hfm-symbols-button" variant="outline" onClick={checkSymbols} disabled={busy === "symbols" || !linked} className={BTN_OUT} title={linked ? "Comprueba que los pares activos cotizan en tu cuenta HFM" : "Vincula primero la cuenta"}>
          {busy === "symbols" ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <ListChecks className="mr-1.5 h-3.5 w-3.5" />} Comprobar símbolos
        </Button>
        {canRedeploy && (
          <Button data-testid="hfm-redeploy-button" variant="outline" onClick={redeploy} disabled={busy === "redeploy"} className={BTN_OUT}>
            {busy === "redeploy" ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="mr-1.5 h-3.5 w-3.5" />} Redesplegar
          </Button>
        )}
        {config.hfm_configured && (
          <Button data-testid="hfm-clear-button" variant="ghost" onClick={clear} disabled={busy === "clear" || config.trading_mode === "live"} title={config.trading_mode === "live" ? "Vuelve a modo paper antes de quitar la cuenta" : undefined}
            className="h-9 font-mono text-[11px] uppercase tracking-wider text-rose-300 hover:bg-rose-500/10 disabled:opacity-40">
            <Trash2 className="mr-1.5 h-3.5 w-3.5" /> Quitar
          </Button>
        )}
      </div>
      {(result || config.hfm_verified_at) && (
        <div data-testid="hfm-test-result" className="space-y-1.5 rounded-sm border border-[#1E293B] bg-[#0B1220] p-3 font-mono text-[11px] text-slate-300">
          {result?.token_valid && <p>Token MetaApi: <span className="text-emerald-400">válido</span> · {result.accounts_total} cuenta(s) en MetaApi</p>}
          {acc && <p>Cuenta {acc.login} · {acc.server} · {String(acc.platform || "").toUpperCase()} · estado <span className={acc.state === "DEPLOYED" ? "text-emerald-400" : "text-amber-300"}>{acc.state}</span> · conexión {acc.connection || "—"} · región {acc.region}</p>}
          {result?.info && (
            <p>Bróker {result.info.broker} · {result.info.currency} · balance <span className="num text-slate-100">{result.info.balance}</span> · equidad <span className="num text-slate-100">{result.info.equity}</span> · margen libre {result.info.freeMargin} · apalancamiento 1:{result.info.leverage} · {result.positions?.length || 0} posiciones abiertas · trading <span className={result.info.tradeAllowed === false ? "text-rose-300" : "text-emerald-400"}>{result.info.tradeAllowed === false ? "NO permitido" : "permitido"}</span></p>
          )}
          {result?.hint && <p className="text-amber-300">{result.hint}</p>}
          {!result && config.hfm_verified_at && <p>Última verificación {fmtDateTime(config.hfm_verified_at)} · {config.hfm_broker || "HFM"} · equidad {config.hfm_verified_equity} {config.hfm_currency} · apalancamiento 1:{config.hfm_leverage}{config.hfm_trade_allowed === false ? " · SIN permiso de trading" : ""}</p>}
        </div>
      )}
      {symbols && <SymbolsCheck data={symbols} />}
    </Panel>
  );
}
