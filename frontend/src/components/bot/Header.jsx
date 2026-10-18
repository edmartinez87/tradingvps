import { useEffect, useState } from "react";
import { Zap, Play, Square, RefreshCw, RotateCcw, Database, Timer, Settings2, LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

const StatusPill = ({ status }) => {
  const { running, scanning } = status;
  const cls = scanning && running
    ? "bg-purple-500/10 text-purple-300 border-purple-500/30"
    : running ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30" : "bg-rose-500/10 text-rose-400 border-rose-500/30";
  const dot = scanning && running ? "bg-purple-400" : running ? "bg-emerald-400" : "bg-rose-400";
  const label = scanning && running ? "Escaneando" : running ? "Bot en ejecución" : "Bot detenido";
  return (
    <span data-testid="bot-status-badge" className={`inline-flex items-center gap-2 rounded-sm border px-2.5 py-1 font-mono text-[11px] font-semibold uppercase tracking-wider ${cls}`}>
      <span className={`pulse-dot ${dot}`} />
      {label}
    </span>
  );
};

export default function Header({ status, onToggle, onScan, onReset, busy, onSettings, onLogout, view }) {
  const [count, setCount] = useState(status.next_scan_in);
  useEffect(() => setCount(status.next_scan_in), [status.next_scan_in]);
  useEffect(() => {
    const id = setInterval(() => setCount((c) => (c > 0 ? c - 1 : c)), 1000);
    return () => clearInterval(id);
  }, []);
  const mirror = status.provider === "bitget";

  return (
    <header data-testid="app-header" className="sticky top-0 z-30 border-b border-[#1E293B] bg-[#07090E]/85 backdrop-blur-xl">
      <div className="flex flex-wrap items-center gap-3 px-4 py-3 md:px-6">
        <div className="mr-auto flex items-center gap-3">
          <div className="logo-mark"><Zap className="h-5 w-5" strokeWidth={2.6} /></div>
          <div>
            <h1 className="font-display text-lg font-extrabold uppercase leading-none tracking-tight md:text-xl">
              Bybit <span className="text-amber-400">AI</span> Trader
            </h1>
            <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.18em] text-slate-500">Futuros perpetuos USDT · Claude Sonnet</p>
          </div>
        </div>

        {status.mode === "REAL" ? (
          <span data-testid="live-mode-badge" className="inline-flex items-center gap-1.5 rounded-sm border border-rose-500/50 bg-rose-500/15 px-2.5 py-1 font-mono text-[11px] font-bold uppercase tracking-wider text-rose-300">
            <span className="pulse-dot bg-rose-400" /> Modo REAL · Bybit {status.env}
          </span>
        ) : (
          <span data-testid="paper-mode-badge" className="rounded-sm border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 font-mono text-[11px] font-semibold uppercase tracking-wider text-amber-400">
            Paper trading
          </span>
        )}
        <TooltipProvider delayDuration={150}>
          <Tooltip>
            <TooltipTrigger asChild>
              <span data-testid="data-source-badge" className="inline-flex cursor-help items-center gap-1.5 rounded-sm border border-[#1E293B] bg-[#0D111A] px-2.5 py-1 font-mono text-[11px] uppercase tracking-wider text-slate-300">
                <Database className="h-3 w-3 text-sky-400" />
                {mirror ? "Datos: Bitget (espejo)" : "Datos: Bybit"}
              </span>
            </TooltipTrigger>
            <TooltipContent className="max-w-xs text-xs">
              {mirror
                ? "Bybit bloquea el acceso desde la región del servidor (EE.UU.). El bot usa precios de futuros perpetuos USDT de Bitget, que replican a Bybit con diferencias mínimas. Desde una región permitida conecta Bybit automáticamente."
                : "Conectado directamente a la API pública v5 de Bybit."}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
        <span data-testid="next-scan-timer" className="inline-flex items-center gap-1.5 font-mono text-[11px] text-slate-400">
          <Timer className="h-3.5 w-3.5" /> Próximo escaneo {count != null ? `${count}s` : "—"}
        </span>
        <StatusPill status={status} />

        <div className="flex flex-wrap items-center gap-2">
          <Button data-testid="scan-now-button" variant="outline" size="sm" onClick={onScan} className="h-8 border-[#1E293B] bg-transparent font-mono text-[11px] uppercase tracking-wider hover:bg-[#111827]">
            <RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Escanear
          </Button>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button data-testid="reset-account-button" variant="outline" size="sm" className="h-8 border-[#1E293B] bg-transparent font-mono text-[11px] uppercase tracking-wider hover:bg-[#111827]">
                <RotateCcw className="mr-1.5 h-3.5 w-3.5" /> Reiniciar
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent data-testid="reset-account-dialog" className="border-[#1E293B] bg-[#0D111A]">
              <AlertDialogHeader>
                <AlertDialogTitle className="font-display">¿Reiniciar la cuenta paper?</AlertDialogTitle>
                <AlertDialogDescription>
                  Se borrarán posiciones, historial, señales y curva de equidad. El balance vuelve al capital inicial configurado (por defecto $500 USDT).
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel data-testid="reset-cancel-button">Cancelar</AlertDialogCancel>
                <AlertDialogAction data-testid="reset-confirm-button" onClick={onReset} className="bg-rose-500 text-white hover:bg-rose-600">
                  Reiniciar cuenta
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
          <Button
            data-testid="bot-toggle-button"
            onClick={onToggle}
            disabled={busy}
            className={`h-8 font-mono text-[11px] font-bold uppercase tracking-wider transition-colors ${
              status.running ? "border border-rose-500/50 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20" : "bg-amber-500 text-[#07090E] hover:bg-amber-400"
            }`}
          >
            {status.running ? <><Square className="mr-1.5 h-3.5 w-3.5" /> Detener bot</> : <><Play className="mr-1.5 h-3.5 w-3.5" /> Iniciar bot</>}
          </Button>
          <Button data-testid="settings-view-button" variant="outline" size="sm" onClick={onSettings}
            className={`h-8 border-[#1E293B] font-mono text-[11px] uppercase tracking-wider hover:bg-[#111827] ${view === "settings" ? "bg-[#111827] text-amber-300" : "bg-transparent"}`}>
            <Settings2 className="mr-1.5 h-3.5 w-3.5" /> {view === "settings" ? "Volver al panel" : "Ajustes"}
          </Button>
          <Button data-testid="logout-button" variant="ghost" size="sm" onClick={onLogout} className="h-8 px-2 font-mono text-[11px] uppercase tracking-wider text-slate-400 hover:bg-[#111827] hover:text-rose-300" title="Cerrar sesión">
            <LogOut className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </header>
  );
}
