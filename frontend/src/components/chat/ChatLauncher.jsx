import { useState } from "react";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ChatPanel } from "./ChatPanel";

// Black & gold "Chatea con IA expert" header button + the sliding chat panel. Shared by both dashboards.
export function ChatLauncher({ bot = "crypto", onApplied }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button data-testid="chat-open-button" size="sm" onClick={() => setOpen(true)} title="Habla con un trader y gestor de riesgo experto que conoce tus tres bots y puede proponerte cambios"
        className="chat-gold-glow h-8 border border-amber-400/80 bg-[#07090E] font-mono text-[11px] font-bold uppercase tracking-wider text-amber-300 transition-transform hover:-translate-y-px hover:bg-[#0D111A] hover:text-amber-200">
        <Sparkles className="mr-1.5 h-3.5 w-3.5 text-amber-400" /> Chatea con IA expert
      </Button>
      <ChatPanel open={open} onOpenChange={setOpen} bot={bot} onApplied={onApplied} />
    </>
  );
}
