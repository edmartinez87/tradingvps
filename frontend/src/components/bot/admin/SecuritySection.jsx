import { useState } from "react";
import { ShieldCheck, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Panel } from "../Panel";
import { http, errMsg, setToken } from "@/lib/api";

export const Field = ({ label, hint, children }) => (
  <div>
    <p className="mb-1 font-mono text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
    {children}
    {hint && <p className="mt-1 text-[11px] text-slate-500">{hint}</p>}
  </div>
);
export const INPUT = "h-9 border-[#1E293B] bg-[#07090E] font-mono text-xs";
export const BTN = "h-9 bg-amber-500 font-mono text-[11px] font-bold uppercase tracking-wider text-[#07090E] hover:bg-amber-400";
export const BTN_OUT = "h-9 border-[#1E293B] bg-transparent font-mono text-[11px] uppercase tracking-wider text-slate-200 hover:bg-[#111827]";

export default function SecuritySection() {
  const [form, setForm] = useState({ current: "", new: "", confirm: "" });
  const [loading, setLoading] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const valid = form.current && form.new.length >= 8 && form.new === form.confirm;

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const { data } = await http.post("/auth/password", { current: form.current, new: form.new });
      setToken(data.token);
      setForm({ current: "", new: "", confirm: "" });
      toast.success("Clave actualizada · las demás sesiones se cerraron");
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Panel testId="security-section" title="Seguridad · clave de acceso" icon={ShieldCheck} bodyClass="p-4">
      <form onSubmit={submit} className="space-y-3">
        <Field label="Clave actual"><Input data-testid="password-current-input" type="password" autoComplete="current-password" value={form.current} onChange={set("current")} className={INPUT} /></Field>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Nueva clave" hint="Mínimo 8 caracteres"><Input data-testid="password-new-input" type="password" autoComplete="new-password" value={form.new} onChange={set("new")} className={INPUT} /></Field>
          <Field label="Repetir nueva clave"><Input data-testid="password-confirm-input" type="password" autoComplete="new-password" value={form.confirm} onChange={set("confirm")} className={INPUT} /></Field>
        </div>
        {form.confirm && form.new !== form.confirm && <p data-testid="password-mismatch" className="text-[11px] text-rose-400">Las claves no coinciden</p>}
        <Button data-testid="password-save-button" type="submit" disabled={!valid || loading} className={BTN}>
          {loading && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />} Cambiar clave
        </Button>
        <p className="font-mono text-[10px] uppercase tracking-wider text-slate-600">Al cambiarla, cualquier otra sesión abierta queda cerrada automáticamente</p>
      </form>
    </Panel>
  );
}
