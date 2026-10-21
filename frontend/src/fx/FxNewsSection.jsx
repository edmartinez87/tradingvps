import { useState } from "react";
import { Newspaper, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Panel } from "@/components/bot/Panel";
import { Field, INPUT, BTN } from "@/components/bot/admin/SecuritySection";

const KEYS = ["news_enabled", "news_interval_min", "news_countries", "news_block_events", "news_event_before_min", "news_event_after_min", "news_block_critical",
  "news_reduce_on_high_risk", "news_size_factor", "news_trading_enabled", "news_trade_min_confidence", "news_trade_confirm_price", "news_trade_window_min",
  "news_trade_max_hours", "news_trade_risk_factor", "news_trade_sl_atr", "news_trade_tp_atr", "news_trade_max_per_event"];
const NUMS = ["news_interval_min", "news_event_before_min", "news_event_after_min", "news_size_factor", "news_trade_min_confidence", "news_trade_window_min",
  "news_trade_max_hours", "news_trade_risk_factor", "news_trade_sl_atr", "news_trade_tp_atr", "news_trade_max_per_event"];
const Toggle = ({ label, hint, checked, onChange, testId }) => (
  <label className="flex cursor-pointer items-center justify-between gap-3 rounded-sm border border-[#1E293B] px-3 py-2">
    <span><span className="block text-[13px] text-slate-200">{label}</span><span className="block text-[11px] text-slate-500">{hint}</span></span>
    <Switch data-testid={testId} checked={checked} onCheckedChange={onChange} />
  </label>
);
const Num = ({ k, label, hint, step, min, max, form, set }) => (
  <Field label={label} hint={hint}>
    <Input data-testid={`fxnews-${k.replace(/_/g, "-")}-input`} type="number" step={step} min={min} max={max} value={form[k]} onChange={(e) => set(k, e.target.value)} className={`${INPUT} num`} />
  </Field>
);

export default function FxNewsSection({ config, onSave }) {
  const [form, setForm] = useState(Object.fromEntries(KEYS.map((k) => [k, config[k]])));
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const toggleCountry = (c) => set("news_countries", form.news_countries.includes(c) ? form.news_countries.filter((x) => x !== c) : [...form.news_countries, c]);

  const save = async () => {
    setBusy(true);
    const body = { ...form };
    NUMS.forEach((k) => { body[k] = Number(body[k]); });
    await onSave(body, "Agente de noticias forex guardado");
    setBusy(false);
  };

  return (
    <Panel testId="fxnews-section" title="Noticias forex y trading por noticias" icon={Newspaper} bodyClass="p-4 space-y-3"
      actions={<Button data-testid="fxnews-save-button" size="sm" onClick={save} disabled={busy || !form.news_countries.length} className={`${BTN} h-7 text-[10px]`}><Save className="mr-1 h-3 w-3" /> Guardar</Button>}>
      <p className="text-[12px] leading-relaxed text-slate-400">
        La IA lee titulares (ForexLive, Investing, FXEmpire, MarketWatch) y la agenda económica de las economías marcadas; el resultado (sesgo por divisa, riesgo por par, alertas)
        entra en la evaluación de cada señal y puede pausar entradas alrededor de eventos de alto impacto. Además, al publicarse un dato ALTO, el bot busca el resultado real en los titulares
        y, si la sorpresa es clara y la confianza supera el umbral, abre una <span className="text-slate-200">operación de noticias</span> con SL/TP por ATR 15m y cierre máximo por tiempo.
      </p>
      <Toggle label="Agente activo" hint="Analiza noticias y agenda de forma periódica (coste IA pequeño por ciclo)" checked={form.news_enabled} onChange={(v) => set("news_enabled", v)} testId="fxnews-enabled-switch" />
      <div>
        <p className="mb-1.5 font-mono text-[10px] uppercase tracking-wider text-slate-500">Economías en la agenda ({form.news_countries.length})</p>
        <div className="flex flex-wrap gap-1.5">
          {(config.news_currencies || []).map((c) => (
            <button key={c} data-testid={`fxnews-country-${c}`} onClick={() => toggleCountry(c)}
              className={`rounded-sm border px-2 py-1 font-mono text-[10px] transition-colors ${form.news_countries.includes(c) ? "border-sky-500/60 bg-sky-500/15 text-sky-300" : "border-[#1E293B] text-slate-500 hover:text-slate-200"}`}>
              {c}
            </button>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <Num k="news_interval_min" label="Intervalo (min)" step={5} min={5} max={240} form={form} set={set} />
        <Num k="news_event_before_min" label="Min. antes del evento" step={5} min={0} max={240} form={form} set={set} />
        <Num k="news_event_after_min" label="Min. después" step={5} min={0} max={240} form={form} set={set} />
      </div>
      <Toggle label="Pausar entradas en eventos de alto impacto" hint="Solo afecta a los pares cuyas divisas publican el dato (y al oro/plata con USD)" checked={form.news_block_events} onChange={(v) => set("news_block_events", v)} testId="fxnews-block-events-switch" />
      <Toggle label="Bloquear pares con noticia crítica" hint="Intervención, crisis, giro de banco central… durante 24 h" checked={form.news_block_critical} onChange={(v) => set("news_block_critical", v)} testId="fxnews-block-critical-switch" />
      <div className="grid grid-cols-[1fr_auto] items-end gap-3">
        <Toggle label="Reducir tamaño con riesgo ALTO" hint="Aplica el factor al riesgo por operación" checked={form.news_reduce_on_high_risk} onChange={(v) => set("news_reduce_on_high_risk", v)} testId="fxnews-reduce-switch" />
        <div className="w-28"><Num k="news_size_factor" label="Factor" step={0.1} min={0.1} max={1} form={form} set={set} /></div>
      </div>
      <div className="rounded-sm border border-sky-500/30 bg-sky-500/[0.06] p-3 space-y-3">
        <Toggle label="Trading por noticias" hint="Opera el dato publicado cuando la sorpresa es clara y la confianza es alta" checked={form.news_trading_enabled} onChange={(v) => set("news_trading_enabled", v)} testId="fxnews-trading-switch" />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Num k="news_trade_min_confidence" label="Confianza mín. (%)" step={5} min={50} max={100} form={form} set={set} />
          <Num k="news_trade_window_min" label="Ventana tras el dato (min)" step={1} min={3} max={60} form={form} set={set} />
          <Num k="news_trade_max_hours" label="Cierre máximo (h)" step={1} min={1} max={48} form={form} set={set} />
          <Num k="news_trade_max_per_event" label="Máx. ops por evento" step={1} min={1} max={4} form={form} set={set} />
          <Num k="news_trade_sl_atr" label="SL (× ATR 15m)" step={0.5} min={0.5} max={5} form={form} set={set} />
          <Num k="news_trade_tp_atr" label="TP (× ATR 15m)" step={0.5} min={1} max={10} form={form} set={set} />
          <Num k="news_trade_risk_factor" label="Factor de riesgo" hint="1 = riesgo normal" step={0.1} min={0.1} max={1.5} form={form} set={set} />
        </div>
        <Toggle label="Exigir confirmación del precio" hint="El par debe haberse movido en la dirección prevista desde la publicación" checked={form.news_trade_confirm_price} onChange={(v) => set("news_trade_confirm_price", v)} testId="fxnews-confirm-switch" />
      </div>
    </Panel>
  );
}
