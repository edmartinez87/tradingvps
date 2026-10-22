import { useState } from "react";
import { Loader2, RotateCcw } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { INPUT } from "./SecuritySection";

// Typed confirmation + upload progress for restoring a backup (stored on the server or picked from the user's disk).
export default function RestoreBackupDialog({ target, word = "RESTAURAR", busy, progress, botsRunning, onConfirm, onClose }) {
  const [typed, setTyped] = useState("");
  const ok = typed.trim().toUpperCase() === word && !botsRunning && !busy;
  return (
    <AlertDialog open={!!target} onOpenChange={(o) => { if (!o && !busy) { setTyped(""); onClose(); } }}>
      <AlertDialogContent data-testid="backup-restore-dialog" className="border-[#1E293B] bg-[#0D111A]">
        <AlertDialogHeader>
          <AlertDialogTitle className="font-display">¿Restaurar {target?.kind === "file" ? "el archivo" : "la copia"} {target?.label}?</AlertDialogTitle>
          <AlertDialogDescription asChild>
            <div className="space-y-2 text-[12px] leading-relaxed text-slate-400">
              <p>Se reemplazan <b className="text-slate-200">todos los datos de ambos bots</b> (ajustes, cuentas, historial, señales, evolución, configuración de IA, Telegram y brókers) por los de la copia. La clave de acceso actual se conserva.</p>
              <p>Tras restaurar, ambos bots quedan <b className="text-slate-200">detenidos</b> para que revises posiciones y ajustes antes de iniciarlos. Las posiciones abiertas en la cuenta real no se tocan en el bróker, pero el bot dejará de seguir las que no estén en la copia.</p>
              {botsRunning && <p data-testid="backup-restore-running-warning" className="rounded-sm border border-amber-500/30 bg-amber-500/10 px-2 py-1.5 text-amber-200">Detén ambos bots (Bybit y HotForex) desde su panel antes de restaurar.</p>}
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="space-y-1.5">
          <p className="font-mono text-[10px] uppercase tracking-wider text-slate-500">Escribe <span className="text-rose-300">{word}</span> para confirmar</p>
          <Input data-testid="backup-restore-confirm-input" value={typed} onChange={(e) => setTyped(e.target.value)} disabled={busy} placeholder={word} className={INPUT} />
          {busy && (
            <div data-testid="backup-restore-progress" className="space-y-1 pt-1">
              <div className="h-1.5 overflow-hidden rounded-full bg-[#1E293B]"><div className="h-full bg-amber-400 transition-[width] duration-300" style={{ width: `${progress}%` }} /></div>
              <p className="font-mono text-[10px] text-slate-500">{progress < 100 ? `Subiendo archivo · ${progress}%` : "Restaurando la base de datos…"}</p>
            </div>
          )}
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel data-testid="backup-restore-cancel" disabled={busy}>Cancelar</AlertDialogCancel>
          <AlertDialogAction data-testid="backup-restore-confirm" disabled={!ok} onClick={(e) => { e.preventDefault(); onConfirm(typed); }} className="bg-rose-500 text-white hover:bg-rose-600 disabled:opacity-40">
            {busy ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="mr-1.5 h-3.5 w-3.5" />} Restaurar
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
