import { useEffect, useRef, useState } from "react";
import { startSwarm, getSwarmLive, generateShipReport } from "@/lib/api";
import { toast } from "sonner";
import { Users, Zap, Activity, Gauge, AlertTriangle, CheckCircle2, TrendingUp, BarChart3 } from "lucide-react";

const PROFILES = [
  { id: "burst", label: "Burst", desc: "0 → target instantly", icon: Zap },
  { id: "ramp", label: "Ramp", desc: "Gradual ramp-up", icon: TrendingUp },
  { id: "soak", label: "Soak", desc: "Sustained load", icon: Activity },
];

const JOURNEYS = [
  { id: "generic", label: "Generic", flow: "Land → Browse → Idle" },
  { id: "ecommerce", label: "E-commerce", flow: "Browse → Cart → Checkout" },
  { id: "finance", label: "Finance", flow: "Login → Transact → Transfer" },
  { id: "saas", label: "SaaS", flow: "Signup → Dashboard → Create" },
];

const USER_PRESETS = [10, 25, 50, 100, 250, 500];

function MetricTile({ label, value, sub, color = "#1D1D1F", testId }) {
  return (
    <div className="rounded-2xl bg-[#F5F5F7] p-5" data-testid={testId}>
      <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B]">{label}</div>
      <div className="font-display text-4xl tabular-nums mt-1" style={{ color }}>{value}</div>
      {sub && <div className="text-xs text-[#86868B] mt-1">{sub}</div>}
    </div>
  );
}

export default function SwarmPanel({ runId }) {
  const [users, setUsers] = useState(50);
  const [profile, setProfile] = useState("burst");
  const [journey, setJourney] = useState("generic");
  const [duration, setDuration] = useState(30);
  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState(null);
  const [events, setEvents] = useState([]);
  const [shipReport, setShipReport] = useState(null);
  const [shipping, setShipping] = useState(false);
  const pollRef = useRef(null);

  // Polling loop while a swarm is running.
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await getSwarmLive(runId);
        if (cancelled) return;
        const s = r.data.summary || {};
        setSummary(s);
        setEvents(r.data.events || []);
        if (s.status === "completed" || s.status === "failed") {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch { /* ignore */ }
    };
    if (busy && !pollRef.current) {
      tick();
      pollRef.current = setInterval(tick, 1500);
    }
    return () => { cancelled = true; if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  }, [busy, runId]);

  // Once we receive completed/failed, drop the busy flag.
  useEffect(() => {
    if (summary?.status === "completed" || summary?.status === "failed") setBusy(false);
  }, [summary?.status]);

  const handleStart = async () => {
    setSummary(null); setEvents([]); setShipReport(null);
    try {
      setBusy(true);
      await startSwarm(runId, {
        target_users: users, profile, journey, duration_secs: duration,
      });
      toast.success(`Launching ${users} virtual users…`);
    } catch (e) {
      setBusy(false);
      toast.error("Could not start swarm", { description: e?.response?.data?.detail || e.message });
    }
  };

  const handleShipReport = async () => {
    setShipping(true);
    try {
      const r = await generateShipReport(runId);
      setShipReport(r.data);
    } catch (e) {
      toast.error("Could not generate Ship Report", { description: e?.response?.data?.detail || e.message });
    } finally {
      setShipping(false);
    }
  };

  const success = summary?.success_rate != null ? (summary.success_rate * 100) : null;
  const p95 = summary?.latency_p95_ms ?? summary?.latency_p95 ?? null;
  const error = summary?.error_rate != null ? summary.error_rate : null;
  const completedAt = summary?.completed_at;
  const recent = events.slice(-12).reverse();

  return (
    <div className="space-y-4" data-testid="swarm-panel">
      {/* Hero / config */}
      <div className="card-elev p-6 md:p-8" data-testid="swarm-config">
        <div className="flex items-start gap-4">
          <div className="h-12 w-12 rounded-2xl bg-[#1D1D1F] flex items-center justify-center shrink-0">
            <Users className="h-6 w-6 text-white" strokeWidth={1.5} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B]">Realistic user swarm</div>
            <div className="font-display text-2xl md:text-3xl mt-1">Spin up real concurrent users.</div>
            <div className="text-sm text-[#86868B] mt-2">
              Atmos drives N Playwright browsers in parallel through a journey on your live URL and reports
              latency, success rate and the user count where things break.
            </div>
          </div>
        </div>

        <div className="mt-6 space-y-5">
          {/* Users */}
          <div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-2">Concurrent users</div>
            <div className="flex flex-wrap gap-2">
              {USER_PRESETS.map((n) => (
                <button
                  key={n}
                  onClick={() => setUsers(n)}
                  data-testid={`swarm-users-${n}`}
                  className={`rounded-full px-4 h-9 text-sm tabular-nums transition-colors ${
                    users === n ? "bg-[#1D1D1F] text-white" : "bg-[#F5F5F7] text-[#1D1D1F] hover:bg-[#EDEDF0]"
                  }`}
                >
                  {n.toLocaleString()}
                </button>
              ))}
            </div>
          </div>

          {/* Profile */}
          <div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-2">Load profile</div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              {PROFILES.map((p) => {
                const Icon = p.icon;
                const active = profile === p.id;
                return (
                  <button
                    key={p.id}
                    onClick={() => setProfile(p.id)}
                    data-testid={`swarm-profile-${p.id}`}
                    className={`text-left rounded-xl p-3 border transition-colors ${
                      active ? "border-[#0071E3] bg-[#F0F7FF]" : "border-black/10 bg-white hover:border-black/20"
                    }`}
                  >
                    <Icon className="h-4 w-4" strokeWidth={1.5} />
                    <div className="font-medium text-sm mt-1">{p.label}</div>
                    <div className="text-xs text-[#86868B]">{p.desc}</div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Journey */}
          <div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-2">User journey</div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {JOURNEYS.map((j) => {
                const active = journey === j.id;
                return (
                  <button
                    key={j.id}
                    onClick={() => setJourney(j.id)}
                    data-testid={`swarm-journey-${j.id}`}
                    className={`text-left rounded-xl p-3 border transition-colors ${
                      active ? "border-[#0071E3] bg-[#F0F7FF]" : "border-black/10 bg-white hover:border-black/20"
                    }`}
                  >
                    <div className="font-medium text-sm">{j.label}</div>
                    <div className="text-xs text-[#86868B] mt-0.5">{j.flow}</div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Duration */}
          <div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-2">Duration</div>
            <div className="flex items-center gap-3">
              <input
                type="range" min={10} max={120} step={5} value={duration}
                onChange={(e) => setDuration(parseInt(e.target.value, 10))}
                className="flex-1 accent-[#0071E3]"
                data-testid="swarm-duration-range"
              />
              <span className="text-sm font-mono bg-[#F5F5F7] px-3 py-1 rounded-md w-16 text-center">{duration}s</span>
            </div>
          </div>

          <button
            onClick={handleStart}
            disabled={busy}
            data-testid="swarm-start"
            className="w-full md:w-auto rounded-full h-11 px-6 bg-[#1D1D1F] text-white text-sm font-medium disabled:opacity-50 inline-flex items-center gap-2"
          >
            <Zap className="h-4 w-4" strokeWidth={2} />
            {busy ? `Running swarm…` : `Launch ${users} virtual users`}
          </button>
        </div>
      </div>

      {/* Live status */}
      {(busy || summary) && (
        <div className="card-elev p-6" data-testid="swarm-metrics">
          <div className="flex items-center justify-between mb-4">
            <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] flex items-center gap-2">
              {summary?.status === "running" || busy
                ? <><span className="w-1.5 h-1.5 rounded-full bg-[#FF3B30] live-dot" /> Live metrics</>
                : summary?.status === "failed" ? <><AlertTriangle className="h-3 w-3 text-[#FF3B30]" /> Failed</>
                : <><CheckCircle2 className="h-3 w-3 text-[#34C759]" /> Completed</>
              }
            </div>
            {completedAt && <div className="text-[11px] text-[#86868B]">{new Date(completedAt).toLocaleString()}</div>}
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <MetricTile label="Users" value={summary?.target_users ?? users} sub={`${profile} · ${journey}`} testId="metric-users" />
            <MetricTile
              label="Success rate"
              value={success == null ? "—" : `${success.toFixed(1)}%`}
              color={success == null ? "#1D1D1F" : success > 95 ? "#34C759" : success > 80 ? "#FF9500" : "#FF3B30"}
              testId="metric-success"
            />
            <MetricTile
              label="P95 latency"
              value={p95 == null ? "—" : `${Math.round(p95)}ms`}
              color={p95 == null ? "#1D1D1F" : p95 < 800 ? "#34C759" : p95 < 1500 ? "#FF9500" : "#FF3B30"}
              testId="metric-p95"
            />
            <MetricTile
              label="Error rate"
              value={error == null ? "—" : `${(error * 100).toFixed(1)}%`}
              color={error == null ? "#1D1D1F" : error < 0.02 ? "#34C759" : error < 0.1 ? "#FF9500" : "#FF3B30"}
              testId="metric-error"
            />
          </div>

          {summary?.breaking_point_users && (
            <div className="mt-4 rounded-xl bg-[#FFF4E5] border border-[#FF9500]/30 p-4 flex gap-3" data-testid="swarm-breakpoint">
              <AlertTriangle className="h-4 w-4 text-[#FF9500] mt-0.5" />
              <div className="text-sm">
                <div className="font-medium">Breaking point: {summary.breaking_point_users.toLocaleString()} concurrent users</div>
                <div className="text-[#86868B] text-xs mt-1">
                  Estimated revenue at risk: ${(summary.revenue_risk_per_hour || 0).toLocaleString()}/hr.
                </div>
              </div>
            </div>
          )}

          {/* Event log */}
          {recent.length > 0 && (
            <div className="mt-5">
              <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-2">Recent activity</div>
              <div className="rounded-xl bg-[#1D1D1F] text-[#F5F5F7] p-3 font-mono text-[11px] max-h-44 overflow-auto" data-testid="swarm-log">
                {recent.map((e, i) => (
                  <div key={i} className="opacity-90 leading-relaxed truncate">
                    <span className="text-[#86868B]">{e.ts ? new Date(e.ts).toLocaleTimeString() : ""}</span>{" "}
                    <span className="text-[#0071E3]">{e.event}</span>{" "}
                    {e.user_id ? `u${e.user_id}` : ""}{" "}
                    {e.status_code ? `· ${e.status_code}` : ""}{" "}
                    {e.error ? `· ${e.error}` : ""}
                  </div>
                ))}
              </div>
            </div>
          )}

          {summary?.status === "completed" && (
            <div className="mt-5 flex flex-wrap gap-2">
              <button
                onClick={handleShipReport}
                disabled={shipping}
                data-testid="swarm-ship-report"
                className="rounded-full h-10 px-5 bg-[#0071E3] text-white text-sm font-medium disabled:opacity-50 inline-flex items-center gap-2"
              >
                <BarChart3 className="h-4 w-4" strokeWidth={2} />
                {shipping ? "Generating…" : "Generate Ship Report"}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Ship report */}
      {shipReport && (
        <div className="card-elev p-6" data-testid="swarm-ship-report-card">
          <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B]">Ship report</div>
          <div className="flex items-baseline gap-3 mt-1">
            <div className="font-display text-3xl">
              {shipReport.readiness === "ship_now" ? "Ship it." :
               shipReport.readiness === "warnings" ? "Ship with care." : "Not ready."}
            </div>
            <div className="text-sm text-[#86868B]">Confidence {shipReport.confidence_score ?? "—"}/100</div>
          </div>
          {shipReport.executive_summary && (
            <p className="text-sm mt-3 text-[#1D1D1F]/80 leading-relaxed">{shipReport.executive_summary}</p>
          )}
          {Array.isArray(shipReport.launch_blockers) && shipReport.launch_blockers.length > 0 && (
            <div className="mt-4 rounded-xl border border-[#FF3B30]/30 bg-[#FFF1F1] p-4">
              <div className="text-[10px] uppercase tracking-[0.2em] text-[#FF3B30] mb-2">Launch blockers</div>
              <ul className="space-y-1 text-sm list-disc pl-4">
                {shipReport.launch_blockers.map((b, i) => <li key={i}>{b}</li>)}
              </ul>
            </div>
          )}
          {Array.isArray(shipReport.recommendations) && shipReport.recommendations.length > 0 && (
            <div className="mt-3">
              <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-2">Recommendations</div>
              <ul className="space-y-1.5 text-sm">
                {shipReport.recommendations.map((r, i) => (
                  <li key={i} className="flex gap-2"><span className="text-[#0071E3]">→</span>{r}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
