import { useEffect, useState } from "react";
import { Zap, Eye, EyeOff, Loader2, LockKeyhole } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { http, setToken, errMsg } from "@/lib/api";

export default function Login({ onLogin }) {
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  useEffect(() => { document.title = "AI Trading · Acceso"; }, []);

  const submit = async (e) => {
    e.preventDefault();
    if (!password) return;
    setLoading(true);
    setError("");
    try {
      const { data } = await http.post("/auth/login", { password });
      setToken(data.token);
      onLogin();
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div data-testid="login-page" className="app-bg grain flex min-h-screen items-center justify-center p-6">
      <form onSubmit={submit} className="panel rise w-full max-w-sm p-8">
        <div className="mb-8 flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-md bg-amber-500 text-[#07090E]"><Zap className="h-5 w-5" strokeWidth={2.5} /></span>
          <div>
            <h1 className="font-display text-lg font-bold uppercase tracking-[0.12em] text-slate-50"><span className="text-amber-400">AI</span> Trading</h1>
            <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-slate-500">Bybit · HotForex · Pepperstone · Panel protegido</p>
          </div>
        </div>
        <label className="mb-1.5 block font-mono text-[10px] uppercase tracking-wider text-slate-500" htmlFor="login-password">Clave de acceso</label>
        <div className="relative">
          <LockKeyhole className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
          <Input id="login-password" data-testid="login-password-input" type={show ? "text" : "password"} autoFocus autoComplete="current-password"
            value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••••••"
            className="h-11 border-[#1E293B] bg-[#07090E] pl-10 pr-10 font-mono text-sm" />
          <button type="button" data-testid="login-toggle-visibility" onClick={() => setShow((s) => !s)} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 transition-colors hover:text-slate-200" aria-label="Mostrar clave">
            {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
        {error && <p data-testid="login-error" className="mt-3 rounded-sm border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[12px] text-rose-300">{error}</p>}
        <Button data-testid="login-submit-button" type="submit" disabled={loading || !password} className="mt-5 h-11 w-full bg-amber-500 font-mono text-[12px] font-bold uppercase tracking-wider text-[#07090E] hover:bg-amber-400">
          {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null} Entrar
        </Button>
        <p className="mt-6 font-mono text-[10px] uppercase tracking-wider text-slate-600">Paper trading · 5 intentos fallidos bloquean el acceso 15 minutos</p>
      </form>
    </div>
  );
}
