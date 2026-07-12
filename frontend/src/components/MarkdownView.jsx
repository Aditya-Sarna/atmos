/** Lightweight markdown renderer — headings, lists, quotes, tables, bold/code. */
export default function MarkdownView({ markdown, className = "" }) {
  if (!markdown) return null;
  const lines = String(markdown).replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let i = 0;

  const inline = (text) => {
    const parts = [];
    const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g;
    let last = 0;
    let m;
    while ((m = re.exec(text)) !== null) {
      if (m.index > last) parts.push(text.slice(last, m.index));
      const tok = m[0];
      if (tok.startsWith("**")) parts.push(<strong key={parts.length}>{tok.slice(2, -2)}</strong>);
      else if (tok.startsWith("`")) parts.push(<code key={parts.length} className="font-mono text-[0.85em] bg-black/5 px-1 rounded">{tok.slice(1, -1)}</code>);
      else parts.push(<em key={parts.length}>{tok.slice(1, -1)}</em>);
      last = m.index + tok.length;
    }
    if (last < text.length) parts.push(text.slice(last));
    return parts;
  };

  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }
    if (line.startsWith("|") && lines[i + 1]?.match(/^\|?\s*-+/)) {
      const rows = [];
      while (i < lines.length && lines[i].startsWith("|")) {
        if (!lines[i].match(/^\|?\s*-+/)) {
          rows.push(lines[i].split("|").slice(1, -1).map((c) => c.trim()));
        }
        i += 1;
      }
      blocks.push(
        <div key={blocks.length} className="overflow-x-auto my-3">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr>{(rows[0] || []).map((c, j) => <th key={j} className="text-left border-b border-black/10 py-1.5 pr-3 font-medium">{inline(c)}</th>)}</tr>
            </thead>
            <tbody>
              {rows.slice(1).map((r, ri) => (
                <tr key={ri} className="border-b border-black/5">
                  {r.map((c, j) => <td key={j} className="py-1.5 pr-3 align-top">{inline(c)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }
    const h = line.match(/^(#{1,3})\s+(.*)$/);
    if (h) {
      const level = h[1].length;
      const Tag = level === 1 ? "h3" : level === 2 ? "h4" : "h5";
      const cls = level === 1 ? "font-display text-xl mt-4 mb-2" : level === 2 ? "font-display text-lg mt-3 mb-1.5" : "font-medium text-sm mt-2 mb-1";
      blocks.push(<Tag key={blocks.length} className={cls}>{inline(h[2])}</Tag>);
      i += 1;
      continue;
    }
    if (line.startsWith("> ")) {
      const quote = [];
      while (i < lines.length && lines[i].startsWith("> ")) {
        quote.push(lines[i].slice(2));
        i += 1;
      }
      blocks.push(
        <blockquote key={blocks.length} className="border-l-2 border-[#FF9500]/50 pl-3 my-2 text-sm text-[#1D1D1F]/75 italic">
          {quote.map((q, qi) => <p key={qi}>{inline(q)}</p>)}
        </blockquote>
      );
      continue;
    }
    if (/^\d+\.\s/.test(line) || line.startsWith("- ")) {
      const ordered = /^\d+\.\s/.test(line);
      const items = [];
      while (i < lines.length && ((ordered && /^\d+\.\s/.test(lines[i])) || (!ordered && (lines[i].startsWith("- ") || lines[i].startsWith("  "))))) {
        if (lines[i].startsWith("  ") && items.length) {
          items[items.length - 1] += ` ${lines[i].trim()}`;
        } else {
          items.push(lines[i].replace(/^\d+\.\s|^-\s/, ""));
        }
        i += 1;
      }
      const List = ordered ? "ol" : "ul";
      blocks.push(
        <List key={blocks.length} className={`my-2 space-y-1.5 text-sm leading-relaxed ${ordered ? "list-decimal pl-5" : "list-disc pl-5"}`}>
          {items.map((it, ii) => <li key={ii}>{inline(it)}</li>)}
        </List>
      );
      continue;
    }
    blocks.push(<p key={blocks.length} className="text-sm leading-relaxed my-2">{inline(line)}</p>);
    i += 1;
  }

  return <div className={`markdown-view text-[#1D1D1F] ${className}`}>{blocks}</div>;
}
