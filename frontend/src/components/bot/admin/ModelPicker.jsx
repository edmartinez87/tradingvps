import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { INPUT } from "./SecuritySection";

const OTHER = "__other__";

export const modelLabel = (m) => {
  const fam = { claude: "Claude", gpt: "GPT", gemini: "Gemini" };
  const out = [];
  m.replace(/-(preview|\d{8})$/, "").split("-").forEach((p) => {
    if (out.length && /^\d+$/.test(p) && /^\d+(\.\d+)?$/.test(out[out.length - 1])) out[out.length - 1] += `.${p}`;
    else out.push(fam[p.toLowerCase()] || p.charAt(0).toUpperCase() + p.slice(1));
  });
  return out.join(" ");
};

export function ModelPicker({ models, value, onChange, testId }) {
  const custom = !models.includes(value);
  return (
    <div className="space-y-2">
      <Select value={custom ? OTHER : value} onValueChange={(v) => onChange(v === OTHER ? "" : v)}>
        <SelectTrigger data-testid={`${testId}-select`} className={INPUT}><SelectValue placeholder="Elige un modelo" /></SelectTrigger>
        <SelectContent className="border-[#1E293B] bg-[#0D111A]">
          {models.map((m) => <SelectItem key={m} value={m} className="font-mono text-xs">{modelLabel(m)} <span className="text-slate-500">· {m}</span></SelectItem>)}
          <SelectItem value={OTHER} className="font-mono text-xs">Otro modelo (escribir)</SelectItem>
        </SelectContent>
      </Select>
      {custom && <Input data-testid={`${testId}-input`} value={value} placeholder="identificador exacto del modelo" onChange={(e) => onChange(e.target.value)} className={INPUT} />}
    </div>
  );
}
