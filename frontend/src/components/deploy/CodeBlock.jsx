import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { toast } from "sonner";

const copyText = async (text) => {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = Object.assign(document.createElement("textarea"), { value: text, style: "position:fixed;opacity:0" });
    document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
  }
};

export function CodeBlock({ cmd, where, testId }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    await copyText(cmd);
    setDone(true); toast.success("Comando copiado");
    setTimeout(() => setDone(false), 1800);
  };
  return (
    <div data-testid={testId} className="group overflow-hidden rounded-sm border border-[#1E293B] bg-[#07090E]">
      <div className="flex items-center justify-between gap-2 border-b border-[#1E293B] bg-[#0B0F17] px-3 py-1">
        <span className="font-mono text-[9.5px] uppercase tracking-[0.18em] text-slate-500">{where}</span>
        <button type="button" data-testid={testId ? `${testId}-copy` : undefined} onClick={copy}
          className="inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-slate-400 transition-colors hover:bg-[#111827] hover:text-emerald-300">
          {done ? <><Check className="h-3 w-3 text-emerald-400" /> Copiado</> : <><Copy className="h-3 w-3" /> Copiar</>}
        </button>
      </div>
      <pre className="thin-scroll overflow-x-auto px-3 py-2.5 font-mono text-[12px] leading-relaxed text-emerald-200"><span className="select-none text-slate-600">$ </span>{cmd}</pre>
    </div>
  );
}
