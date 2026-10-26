import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { api, errMsg } from "@/lib/api";

// Global (both bots): the chat lives under /api/chat regardless of which dashboard is open.
const CHAT = "/chat";
const POLL_MS = 1500;

export function useChat(open, bot, onApplied) {
  const [state, setState] = useState(null);
  const [job, setJob] = useState(null);
  const [resolving, setResolving] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const pollRef = useRef(null);

  const stopPoll = () => { if (pollRef.current) clearTimeout(pollRef.current); pollRef.current = null; };

  const finishJob = useCallback((j) => {
    stopPoll();
    setJob(null);
    if (j?.result) {
      setState((s) => ({ ...s, messages: [...s.messages.filter((m) => m.id !== "tmp"), j.result.user, j.result.assistant], session: { ...s.session, n_messages: j.result.n_messages } }));
      if (j.result.assistant.proposals?.length) toast.message("La IA te ha dejado una propuesta: revísala y pulsa Aplicar o Descartar");
    }
  }, []);

  const poll = useCallback((id) => {
    stopPoll();
    pollRef.current = setTimeout(async () => {
      try {
        const { data } = await api.get(`${CHAT}/jobs/${id}`);
        if (data.status === "running") { setJob(data); poll(id); } else finishJob(data);
      } catch (e) {
        stopPoll(); setJob(null);
        toast.error(errMsg(e));
        api.get(CHAT).then((r) => setState(r.data)).catch(() => {});
      }
    }, POLL_MS);
  }, [finishJob]);

  const load = useCallback(() => api.get(CHAT).then((r) => {
    setState(r.data); setLoadError(null);
    if (r.data.job?.status === "running") { setJob(r.data.job); poll(r.data.job.id); }
  }).catch((e) => setLoadError(errMsg(e))), [poll]);

  useEffect(() => { if (open) load(); else stopPoll(); return stopPoll; }, [open, load]);

  const send = async (text) => {
    setState((s) => ({ ...s, messages: [...s.messages, { id: "tmp", role: "user", content: text, ts: new Date().toISOString(), proposals: [], tools: [] }] }));
    try {
      const { data } = await api.post(`${CHAT}/message`, { text, panel: bot });
      setJob(data); poll(data.id);
      return true;
    } catch (e) {
      toast.error(errMsg(e));
      setState((s) => ({ ...s, messages: s.messages.filter((m) => m.id !== "tmp") }));
      return false;
    }
  };

  const resolve = async (id, apply) => {
    setResolving(id);
    try {
      const { data } = await api.post(`${CHAT}/proposals/${id}/${apply ? "apply" : "discard"}`);
      setState((s) => ({ ...s, messages: [...s.messages.map((m) => ({ ...m, proposals: (m.proposals || []).map((p) => (p.id === id ? data.proposal : p)) })), data.event] }));
      if (data.proposal.status === "applied") { toast.success(data.proposal.result); onApplied?.(); }
      else if (data.proposal.status === "failed") toast.error(data.proposal.result);
      else toast.message("Propuesta descartada");
    } catch (e) {
      toast.error(errMsg(e));
      load();
    } finally {
      setResolving(null);
    }
  };

  const reset = async () => {
    try { const { data } = await api.post(`${CHAT}/new`); setState(data); toast.success("Conversación nueva · la memoria duradera se conserva"); }
    catch (e) { toast.error(errMsg(e)); }
  };

  const saveMemory = async (notes) => {
    try { const { data } = await api.put(`${CHAT}/memory`, { notes }); setState((s) => ({ ...s, memory: data.notes })); return true; }
    catch (e) { toast.error(errMsg(e)); return false; }
  };

  return { state, job, resolving, loadError, send, resolve, reset, saveMemory, reload: load };
}
