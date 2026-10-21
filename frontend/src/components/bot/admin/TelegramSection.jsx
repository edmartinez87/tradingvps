import { useState } from "react";
import { Send, Loader2, Radar, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Panel } from "../Panel";
import { http, errMsg } from "@/lib/api";
import { Field, INPUT, BTN, BTN_OUT } from "./SecuritySection";
import WeeklySummaryCard from "./WeeklySummaryCard";

const ALERTS = [
  ["orders", "Entradas, salidas y límite diario"],
  ["ai", "Decisiones de la IA sobre cada señal"],
  ["daily", "Resumen diario (00:00 UTC) y semanal (domingos 20:00 UTC)"],
  ["plan", "Avisos del plan de crecimiento"],
  ["review", "Revisión IA automática y revalidación walk-forward"],
  ["news", "Alertas de noticias graves y eventos macro"],
  ["system", "Conexión con el bróker (HFM/MetaApi) caída o restablecida"],
];

export default function TelegramSection({ config, onSave, showWeekly = true, weeklyDesc }) {
  const [form, setForm] = useState({ telegram_enabled: config.telegram_enabled, telegram_bot_token: "", telegram_chat_id: config.telegram_chat_id, telegram_alerts: config.telegram_alerts });
  const [chats, setChats] = useState(null);
  const [busy, setBusy] = useState("");
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const save = async () => {
    setBusy("save");
    const ok = await onSave(form, "Telegram guardado");
    setBusy("");
    if (ok) set("telegram_bot_token", "");
  };
  const detect = async () => {
    setBusy("detect");
    try {
      const { data } = await http.post("/telegram/chats", { token: form.telegram_bot_token });
      setChats(data);
      if (!data.chats.length) toast.info(`Bot @${data.bot.username} válido. Escríbele un mensaje en Telegram y vuelve a detectar.`);
    } catch (e) {
      toast.error(errMsg(e));
    } finally {
      setBusy("");
    }
  };
  const test = async () => {
    setBusy("test");
    try {
      await http.post("/telegram/test");
      toast.success("Mensaje de prueba enviado a Telegram");
    } catch (e) {
      toast.error(errMsg(e));
    } finally {
      setBusy("");
    }
  };

  return (
    <Panel testId="telegram-section" title="Alertas de Telegram" icon={Send} bodyClass="p-4 space-y-3"
      actions={<label className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-slate-400">Activo <Switch data-testid="telegram-enabled-switch" checked={form.telegram_enabled} onCheckedChange={(v) => set("telegram_enabled", v)} /></label>}>
      <p className="text-[12px] leading-relaxed text-slate-400">
        1) En Telegram abre <span className="text-slate-200">@BotFather</span> → <span className="font-mono">/newbot</span> y copia el token. 2) Escríbele cualquier mensaje a tu bot. 3) Pulsa «Detectar chat ID».
        {config.telegram_ready && <span data-testid="telegram-ready-badge" className="ml-2 inline-flex items-center gap-1 text-emerald-400"><CheckCircle2 className="h-3 w-3" /> Conectado</span>}
      </p>
      <Field label={`Token del bot${config.telegram_bot_token ? ` · guardado ${config.telegram_bot_token}` : ""}`} hint="Déjalo vacío para mantener el guardado.">
        <Input data-testid="telegram-token-input" type="password" autoComplete="off" value={form.telegram_bot_token} placeholder={config.telegram_bot_token || "123456789:AAH…"} onChange={(e) => set("telegram_bot_token", e.target.value)} className={INPUT} />
      </Field>
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[180px] flex-1">
          <Field label="Chat ID"><Input data-testid="telegram-chat-id-input" value={form.telegram_chat_id} placeholder="123456789 o -100…" onChange={(e) => set("telegram_chat_id", e.target.value)} className={INPUT} /></Field>
        </div>
        <Button data-testid="telegram-detect-button" variant="outline" onClick={detect} disabled={busy === "detect"} className={BTN_OUT}>
          {busy === "detect" ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Radar className="mr-1.5 h-3.5 w-3.5" />} Detectar chat ID
        </Button>
      </div>
      {chats && (
        <div data-testid="telegram-chats" className="rounded-sm border border-[#1E293B] bg-[#0D111A] p-2 text-[12px]">
          <p className="mb-1 font-mono text-[10px] uppercase tracking-wider text-slate-500">Bot @{chats.bot.username} · chats detectados</p>
          {chats.chats.length === 0 && <p className="text-slate-500">Ningún chat todavía: envía un mensaje al bot y vuelve a detectar.</p>}
          {chats.chats.map((c) => (
            <button key={c.id} data-testid={`telegram-chat-${c.id}`} onClick={() => set("telegram_chat_id", c.id)} className="flex w-full items-center justify-between rounded-sm px-2 py-1 text-left transition-colors hover:bg-[#111827]">
              <span className="text-slate-200">{c.name} <span className="text-slate-500">· {c.type}</span></span><span className="font-mono text-amber-300">{c.id}</span>
            </button>
          ))}
        </div>
      )}
      <div className="space-y-1.5">
        <p className="font-mono text-[10px] uppercase tracking-wider text-slate-500">Qué avisar</p>
        {ALERTS.map(([k, label]) => (
          <label key={k} className="flex cursor-pointer items-center justify-between gap-3 rounded-sm border border-[#1E293B] px-3 py-1.5 text-[12px] text-slate-200">
            {label}
            <Switch data-testid={`telegram-alert-${k}-switch`} checked={form.telegram_alerts[k] !== false} onCheckedChange={(v) => set("telegram_alerts", { ...form.telegram_alerts, [k]: v })} />
          </label>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button data-testid="telegram-save-button" onClick={save} disabled={busy === "save"} className={BTN}>{busy === "save" && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />} Guardar</Button>
        <Button data-testid="telegram-test-button" variant="outline" onClick={test} disabled={busy === "test" || !config.telegram_ready} className={BTN_OUT}>
          {busy === "test" ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Send className="mr-1.5 h-3.5 w-3.5" />} Enviar prueba
        </Button>
      </div>
      {showWeekly && <WeeklySummaryCard ready={!!config.telegram_ready} desc={weeklyDesc} />}
    </Panel>
  );
}
