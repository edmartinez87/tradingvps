// Light Markdown renderer for assistant replies (headings, bold/italic/code, lists, code blocks). No external deps.
const inline = (text) => {
  const out = [];
  const re = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*\n]+\*)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    if (t.startsWith("`")) out.push(<code key={m.index} className="rounded-sm bg-black/50 px-1 py-0.5 font-mono text-[11px] text-amber-200">{t.slice(1, -1)}</code>);
    else if (t.startsWith("**")) out.push(<strong key={m.index} className="font-semibold text-amber-50">{t.slice(2, -2)}</strong>);
    else out.push(<em key={m.index} className="text-slate-200">{t.slice(1, -1)}</em>);
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
};

const H_CLS = { 1: "mt-3 text-[15px] font-bold text-amber-200", 2: "mt-3 text-[14px] font-bold text-amber-200", 3: "mt-2 text-[13px] font-semibold text-amber-100" };

export function Markdown({ text }) {
  const blocks = [];
  const lines = (text || "").split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim().startsWith("```")) {
      const code = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) code.push(lines[i++]);
      i += 1;
      blocks.push(<pre key={blocks.length} className="my-2 overflow-x-auto rounded-sm border border-[#1E293B] bg-black/60 p-3 font-mono text-[11px] leading-relaxed text-slate-200">{code.join("\n")}</pre>);
      continue;
    }
    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    if (h) { const lvl = h[1].length; blocks.push(<p key={blocks.length} className={H_CLS[lvl]}>{inline(h[2])}</p>); i += 1; continue; }
    if (/^\s*([-*•]|\d+[.)])\s+/.test(line)) {
      const items = [];
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      while (i < lines.length && /^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*•]|\d+[.)])\s+/, ""));
      const Tag = ordered ? "ol" : "ul";
      blocks.push(<Tag key={blocks.length} className={`my-1.5 space-y-1 pl-5 ${ordered ? "list-decimal" : "list-disc"} marker:text-amber-400`}>{items.map((it, k) => <li key={k}>{inline(it)}</li>)}</Tag>);
      continue;
    }
    if (line.trim().startsWith("|")) {
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(lines[i++]);
      blocks.push(<pre key={blocks.length} className="my-2 overflow-x-auto rounded-sm bg-black/40 p-2 font-mono text-[10.5px] leading-relaxed text-slate-300">{rows.filter((r) => !/^\|[\s:-|]+\|$/.test(r.trim())).join("\n")}</pre>);
      continue;
    }
    if (!line.trim()) { i += 1; continue; }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,3})\s/.test(lines[i]) && !/^\s*([-*•]|\d+[.)])\s+/.test(lines[i]) && !lines[i].trim().startsWith("```") && !lines[i].trim().startsWith("|")) para.push(lines[i++]);
    blocks.push(<p key={blocks.length} className="my-1.5 leading-relaxed">{para.map((p, k) => <span key={k}>{inline(p)}{k < para.length - 1 && <br />}</span>)}</p>);
  }
  return <div className="text-[13px] text-slate-200">{blocks}</div>;
}
