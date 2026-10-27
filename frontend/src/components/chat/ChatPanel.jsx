import { useEffect, useRef, useState } from "react";
import { Sparkles, Send, Loader2, Brain, RotateCcw, Cpu, ShieldCheck, Code2, Lightbulb, Activity, FileText } from "lucide-react";
import { Sheet, SheetContent, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { useChat } from "./useChat";
import { BOT_NAMES } from "@/fx/brand";

const CHIP = { fx: "border-sky-500/40 text-sky-300", pepper: "border-teal-500/40 text-teal-300", crypto: "border-amber-500/40 text-amber-300" };
import { ChatMessage } from "./ChatMessage";
import { MemoryDialog } from "./MemoryDialog";

const SUGGESTIONS = (bot) => [
  { Icon: Activity, text: `Revisa el estado y el rendimiento del bot ${BOT_NAMES[bot] || "Bybit"} y dime qué mejorarías` },
  { Icon: ShieldCheck, text: "¿Qué riesgo estoy asumiendo ahora mismo con las posiciones abiertas y los ajustes actuales?" },
  { Icon: Lightbulb, text: "Propón una configuración más prudente para las próximas semanas" },
  { Icon: Code2, text: "Explícame cómo decide el bot el tamaño de cada operación leyendo el código" },
  { Icon: FileText, text: "¿Qué dicen las últimas señales y por qué la IA rechazó algunas?" },
];

function Thinking({ job }) {
  const steps = job?.steps || [];
  const last = steps[steps.length - 1] || "Pensando";
  return (
    <div data-testid="chat-thinking" className="flex gap-2.5">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-sm border border-amber-400/50 bg-gradient-to-br from-amber-400/20 to-black text-amber-300">
        <Sparkles className="h-3.5 w-3.5 animate-pulse" />
      </div>
      <div className="rounded-md rounded-tl-sm border border-amber-400/20 bg-[#0D111A] px-3.5 py-2.5">
        <div className="flex items-center gap-2 font-mono text-[11px] text-amber-200"><Loader2 className="h-3.5 w-3.5 animate-spin" /> {last}…</div>
        {steps.length > 1 && <p className="mt-1 font-mono text-[9.5px] text-slate-500">{steps.slice(0, -1).join(" · ")}</p>}
      </div>
    </div>
  );
}

export function ChatPanel({ open, onOpenChange, bot, onApplied }) {
  const { state, job, resolving, loadError, send, resolve, reset, saveMemory, reload } = useChat(open, bot, onApplied);
  const [text, setText] = useState("");
  const [memOpen, setMemOpen] = useState(false);
  const endRef = useRef(null);
  const taRef = useRef(null);
  const n = state?.messages?.length || 0;
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [n, job?.steps?.length, open]);
  useEffect(() => { if (open) setTimeout(() => taRef.current?.focus(), 350); }, [open]);
  useEffect(() => { if (open && !job) setTimeout(() => taRef.current?.focus(), 50); }, [job, open]);
  useEffect(() => { document.body.classList.toggle("chat-open", open); return () => document.body.classList.remove("chat-open"); }, [open]);

  const submit = async (t) => {
    const msg = (t ?? text).trim();
    if (!msg || job) return;
    setText("");
    if (!(await send(msg))) setText(msg);
  };
  const onKey = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } };
  const summaries = state?.session?.summaries || 0;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent data-testid="chat-panel" side="right" className="flex w-full flex-col gap-0 border-l border-amber-500/30 bg-[#07090E] p-0 text-slate-200 sm:max-w-[560px] [&>button]:text-slate-400 [&>button]:hover:text-amber-300">
        <div className="chat-gold-bar border-b border-[#1E293B] px-5 pb-3 pt-4">
          <div className="flex items-center gap-3 pr-8">
            <div className="flex h-9 w-9 items-center justify-center rounded-sm border border-amber-400/60 bg-gradient-to-br from-amber-400/25 via-black to-black text-amber-300 shadow-[0_0_16px_rgba(247,166,0,0.25)]">
              <Sparkles className="h-4.5 w-4.5" />
            </div>
            <div className="min-w-0 flex-1">
              <SheetTitle className="font-display text-base font-extrabold uppercase tracking-tight text-amber-100">IA <span className="text-amber-400">expert</span></SheetTitle>
              <SheetDescription data-testid="chat-subtitle" className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">
                <span>Trader y gestor de riesgo · {state?.ai?.label || "IA"}</span>
                <span data-testid="chat-panel-chip" className={`rounded-sm border px-1.5 py-0.5 text-[9.5px] tracking-wider ${CHIP[bot] || CHIP.crypto}`}>panel {BOT_NAMES[bot] || "Bybit"}</span>
              </SheetDescription>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button data-testid="chat-memory-button" variant="outline" size="sm" onClick={() => setMemOpen(true)} className="h-7 border-[#1E293B] bg-transparent px-2 font-mono text-[10px] uppercase tracking-wider text-slate-300 hover:bg-[#111827]">
              <Brain className="mr-1.5 h-3 w-3 text-amber-400" /> Memoria ({state?.memory?.length || 0})
            </Button>
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button data-testid="chat-new-button" variant="outline" size="sm" disabled={!!job || !state} className="h-7 border-[#1E293B] bg-transparent px-2 font-mono text-[10px] uppercase tracking-wider text-slate-300 hover:bg-[#111827]">
                  <RotateCcw className="mr-1.5 h-3 w-3" /> Nueva conversación
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent data-testid="chat-new-dialog" className="border-[#1E293B] bg-[#0D111A]">
                <AlertDialogHeader>
                  <AlertDialogTitle className="font-display">¿Empezar una conversación nueva?</AlertDialogTitle>
                  <AlertDialogDescription>Se archiva la conversación actual (y sus propuestas pendientes). La memoria duradera —tus preferencias y objetivos— se conserva.</AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel data-testid="chat-new-cancel">Cancelar</AlertDialogCancel>
                  <AlertDialogAction data-testid="chat-new-confirm" onClick={reset} className="bg-amber-500 text-[#07090E] hover:bg-amber-400">Empezar de cero</AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
            <span data-testid="chat-context-info" className="ml-auto inline-flex items-center gap-1 font-mono text-[9.5px] uppercase tracking-wider text-slate-500" title={`La conversación se resume automáticamente cada ${state?.config?.summary_every || 40} mensajes conservando los últimos ${state?.config?.keep_last || 10}`}>
              <Cpu className="h-3 w-3" /> {state?.session?.n_messages || 0} msgs{summaries > 0 ? ` · ${summaries} ${summaries === 1 ? "resumen" : "resúmenes"}` : ""}
            </span>
          </div>
        </div>

        <div data-testid="chat-messages" className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
          {!state && !loadError && <div className="flex items-center justify-center gap-2 py-10 font-mono text-[11px] text-slate-500"><Loader2 className="h-3.5 w-3.5 animate-spin text-amber-400" /> Cargando la conversación…</div>}
          {loadError && (
            <div data-testid="chat-load-error" className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 font-mono text-[11px] text-rose-200">
              No se pudo cargar el chat: {loadError} <button onClick={reload} className="ml-2 underline">Reintentar</button>
            </div>
          )}
          {state?.ai_health?.ok === false && (
            <div data-testid="chat-ai-down" className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 font-mono text-[11px] text-rose-200">
              La IA está sin servicio ({state.ai_health.label}): {state.ai_health.error}
            </div>
          )}
          {state && n === 0 && (
            <div data-testid="chat-empty" className="space-y-4 pt-2">
              <div className="rounded-md border border-[#1E293B] bg-[#0D111A] p-4">
                <p className="text-[13px] leading-relaxed text-slate-300">
                  Hola. Veo en vivo los dos bots (ajustes, cuenta, posiciones, señales, logs, noticias) y puedo leer el código para explicarte cómo funciona cualquier cosa.
                  Si me pides un cambio o una acción te dejaré una <span className="text-amber-200">tarjeta con Aplicar / Descartar</span>: nada se ejecuta sin tu confirmación.
                </p>
                <p className="mt-2 font-mono text-[10px] uppercase tracking-wider text-slate-500">Nunca toco credenciales, modo REAL ni código.</p>
              </div>
              <div className="space-y-1.5">
                <p className="font-mono text-[10px] uppercase tracking-wider text-slate-500">Prueba con…</p>
                {SUGGESTIONS(bot).map((s, i) => (
                  <button key={i} data-testid={`chat-suggestion-${i}`} onClick={() => submit(s.text)}
                    className="flex w-full items-start gap-2.5 rounded-sm border border-[#1E293B] bg-transparent px-3 py-2 text-left text-[12.5px] leading-snug text-slate-300 transition-colors hover:border-amber-400/50 hover:bg-amber-500/5 hover:text-amber-100">
                    <s.Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" /> {s.text}
                  </button>
                ))}
              </div>
            </div>
          )}
          {state?.messages.map((m) => <ChatMessage key={m.id} m={m} onResolve={resolve} resolving={resolving} />)}
          {job && <Thinking job={job} />}
          <div ref={endRef} />
        </div>

        <div className="border-t border-[#1E293B] bg-[#0A0D14] px-4 py-3">
          <div className="flex items-end gap-2 rounded-md border border-[#1E293B] bg-[#07090E] px-3 py-2 transition-colors focus-within:border-amber-400/60">
            <textarea ref={taRef} data-testid="chat-input" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey} rows={1} maxLength={6000} disabled={!state || !!job}
              placeholder={job ? "La IA está respondiendo…" : "Pregunta, pide un análisis o propón un cambio… (Enter envía · Shift+Enter salto de línea)"}
              className="max-h-40 min-h-[24px] flex-1 resize-none bg-transparent text-[13px] leading-relaxed text-slate-100 placeholder:text-slate-600 focus:outline-none"
              onInput={(e) => { e.target.style.height = "auto"; e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`; }} />
            <Button data-testid="chat-send-button" size="sm" onClick={() => submit()} disabled={!text.trim() || !!job || !state}
              className="h-8 w-8 shrink-0 bg-amber-500 p-0 text-[#07090E] hover:bg-amber-400 disabled:opacity-40">
              {job ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            </Button>
          </div>
          <p className="mt-1.5 font-mono text-[9.5px] uppercase tracking-wider text-slate-600">Conversación compartida por ambos bots · los cambios requieren tu confirmación</p>
        </div>
        <MemoryDialog open={memOpen} onOpenChange={setMemOpen} notes={state?.memory || []} onSave={saveMemory} />
      </SheetContent>
    </Sheet>
  );
}
