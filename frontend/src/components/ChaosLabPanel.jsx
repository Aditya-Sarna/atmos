import { useEffect, useMemo, useRef, useState } from "react";
import { startChaos, getChaosLive, setChaosTargets } from "@/lib/api";
import { toast } from "sonner";
import {
  Activity, AlertTriangle, Gauge, Layers, Radio, ShieldAlert, Zap,
} from "lucide-react";

const HEALTH_COLOR = {
  idle: "#86868B",
  healthy: "#34C759",
  degraded: "#FF9500",
  critical: "#FF3B30",
  broken: "#FF3B30",
};

function Metric({ label, value, sub }) {
  return (
    <div className="rounded-2xl bg-[#F5F5F7] p-4">
      <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B]">{label}</div>
      <div className="font-display text-3xl tabular-nums mt-1">{value}</div>
      {sub && <div className="text-xs text-[#86868B] mt-1">{sub}</div>}
    </div>
  );
}

function ArchitectureDiagram({ nodes = [], edges = [] }) {
  const layout = useMemo(() => {
    const cols = {
      client: 40,
      edge: 160,
      route: 300,
      api: 460,
      payment: 460,
      data: 620,
    };
    const byKind = {};
    nodes.forEach((n) => {
      byKind[n.kind] = byKind[n.kind] || [];
      byKind[n.kind].push(n);
    });
    const positioned = [];
    Object.entries(byKind).forEach(([kind, list]) => {
      list.forEach((n, i) => {
        positioned.push({
          ...n,
          x: cols[kind] ?? 300,
          y: 40 + i * 70 + (kind === "payment" ? 120 : 0),
        });
      });
    });
    return positioned;
  }, [nodes]);

  const byId = Object.fromEntries(layout.map((n) => [n.id, n]));

  return (
    <div className="rounded-2xl bg-[#1D1D1F] p-4 overflow-x-auto" data-testid="chaos-architecture">
      <div className="text-[10px] uppercase tracking-[0.2em] text-white/40 mb-3 flex items-center gap-2">
        <Radio className="h-3 w-3 text-[#FF3B30] live-dot" /> Live architecture stream
      </div>
      <svg viewBox="0 0 700 280" className="w-full min-w-[640px] h-[280px]">
        {edges.map((e, i) => {
          const a = byId[e.from];
          const b = byId[e.to];
          if (!a || !b) return null;
          return (
            <line
              key={i}
              x1={a.x + 50}
              y1={a.y + 18}
              x2={b.x}
              y2={b.y + 18}
              stroke="rgba(255,255,255,0.15)"
              strokeWidth="1.5"
            />
          );
        })}
        {layout.map((n) => (
          <g key={n.id} transform={`translate(${n.x}, ${n.y})`}>
            <rect
              width="100"
              height="44"
              rx="10"
              fill="rgba(255,255,255,0.06)"
              stroke={HEALTH_COLOR[n.health] || "#86868B"}
              strokeWidth="2"
            />
            <text x="8" y="18" fill="#fff" fontSize="10" fontFamily="system-ui">
              {n.label.length > 14 ? `${n.label.slice(0, 13)}…` : n.label}
            </text>
            <text x="8" y="34" fill={HEALTH_COLOR[n.health] || "#86868B"} fontSize="9" fontFamily="system-ui">
              {n.health}
              {n.latency_p95_ms ? ` · ${Math.round(n.latency_p95_ms)}ms` : ""}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

export default function ChaosLabPanel({ runId, projectId, pages = [] }) {
  const [scope, setScope] = useState("app");
  const [selected, setSelected] = useState([]);
  const [mode, setMode] = useState("crash");
  const [users, setUsers] = useState(25);
  const [maxUsers, setMaxUsers] = useState(200);
  const [includePayments, setIncludePayments] = useState(true);
  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState(null);
  const [events, setEvents] = useState([]);
  const [liveNodes, setLiveNodes] = useState([]);
  const [liveEdges, setLiveEdges] = useState([]);
  const pollRef = useRef(null);

  useEffect(() => {
    if (pages?.length && selected.length === 0) {
      setSelected(pages.slice(0, 4).map((p) => p.url || p));
    }
  }, [pages]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await getChaosLive(runId);
        if (cancelled) return;
        const s = r.data.summary || {};
        setSummary(s);
        setEvents(r.data.events || []);
        const arch = s.architecture || s.live?.architecture;
        if (arch?.nodes) setLiveNodes(arch.nodes);
        if (arch?.edges) setLiveEdges(arch.edges);
        const archEv = [...(r.data.events || [])].reverse().find((e) => e.event === "chaos_architecture" || e.type === "chaos_architecture");
        if (archEv?.nodes) setLiveNodes(archEv.nodes);
        if (s.status === "completed" || s.status === "failed") {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setBusy(false);
        }
      } catch { /* ignore */ }
    };
    if (busy && !pollRef.current) {
      tick();
      pollRef.current = setInterval(tick, 1200);
    }
    return () => {
      cancelled = true;
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [busy, runId]);

  const togglePage = (url) => {
    setSelected((prev) => (prev.includes(url) ? prev.filter((u) => u !== url) : [...prev, url]));
  };

  const handleStart = async () => {
    try {
      setBusy(true);
      setSummary(null);
      setEvents([]);
      if (projectId) {
        await setChaosTargets(projectId, {
          scope,
          pages: scope === "pages" ? selected : [],
          include_payments: includePayments,
          source: "ui",
        }).catch(() => {});
      }
      await startChaos(runId, {
        scope,
        pages: scope === "pages" ? selected : undefined,
        mode,
        users,
        max_users: maxUsers,
        hold_secs: 10,
        include_payments: includePayments,
        payment_provider: "stripe",
        step_factor: 2,
      });
      toast.success(mode === "crash" ? "Crash test started — ramping until break" : `Fixed load · ${users} users`);
    } catch (e) {
      setBusy(false);
      toast.error("Chaos Lab failed to start", { description: e?.response?.data?.detail || e.message });
    }
