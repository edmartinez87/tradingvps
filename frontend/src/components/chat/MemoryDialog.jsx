import { useEffect, useState } from "react";
import { Brain, Trash2, Plus, Loader2 } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fmtDateTime } from "@/lib/api";

export function MemoryDialog({ open, onOpenChange, notes, onSave }) {
  const [draft, setDraft] = useState(notes || []);
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (open) setDraft(notes || []); }, [open, notes]);
  const dirty = JSON.stringify(draft) !== JSON.stringify(notes || []);

  const add = () => {
    const t = text.trim().slice(0, 160);
    if (!t) return;
    setDraft((d) => [...d, { text: t, ts: new Date().toISOString() }]);
    setText("");
  };
  const save = async () => { setSaving(true); if (await onSave(draft)) onOpenChange(false); setSaving(false); };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="chat-memory-dialog" className="border-[#1E293B] bg-[#0D111A] sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 font-display text-amber-200"><Brain className="h-4 w-4 text-amber-400" /> Memoria duradera</DialogTitle>
          <DialogDescription className="text-[12px] text-slate-400">
            Hechos, preferencias y objetivos que la IA recuerda en todas las conversaciones. La IA los actualiza al resumir; aquí puedes añadir o quitar notas a mano.
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-72 space-y-1.5 overflow-y-auto pr-1">
          {draft.length === 0 && <p data-testid="chat-memory-empty" className="py-4 text-center font-mono text-[11px] text-slate-500">Todavía no hay nada guardado. Pídele a la IA «recuerda que…» o añade una nota.</p>}
          {draft.map((n, i) => (
            <div key={`${n.text}-${i}`} data-testid={`chat-memory-note-${i}`} className="flex items-start gap-2 rounded-sm border border-[#1E293B] bg-[#07090E] px-2.5 py-2">
              <div className="min-w-0 flex-1">
                <p className="text-[12.5px] leading-snug text-slate-200">{n.text}</p>
                <p className="mt-0.5 font-mono text-[9.5px] text-slate-500">{fmtDateTime(n.ts)}</p>
              </div>
              <button data-testid={`chat-memory-delete-${i}`} onClick={() => setDraft((d) => d.filter((_, k) => k !== i))} className="rounded-sm p-1 text-slate-500 transition-colors hover:bg-rose-500/10 hover:text-rose-300" title="Quitar nota">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
        <div className="flex gap-2">
          <Input data-testid="chat-memory-input" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} maxLength={160}
            placeholder="Nueva nota (máx. 160 caracteres)" className="h-9 border-[#1E293B] bg-[#07090E] text-[12.5px]" />
          <Button data-testid="chat-memory-add" variant="outline" size="sm" onClick={add} disabled={!text.trim()} className="h-9 border-[#1E293B] bg-transparent font-mono text-[11px] uppercase tracking-wider hover:bg-[#111827]">
            <Plus className="h-3.5 w-3.5" />
          </Button>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)} className="font-mono text-[11px] uppercase tracking-wider text-slate-400">Cerrar</Button>
          <Button data-testid="chat-memory-save" size="sm" disabled={!dirty || saving} onClick={save} className="bg-amber-500 font-mono text-[11px] font-bold uppercase tracking-wider text-[#07090E] hover:bg-amber-400">
            {saving && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />} Guardar memoria
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
