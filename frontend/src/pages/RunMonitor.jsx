import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getRun, BACKEND_URL } from "@/lib/api";
import SiteHeader from "@/components/SiteHeader";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import AtmosMark from "@/components/AtmosMark";
import { TestCaseList, TestCaseTheatre } from "@/components/TestCases";
import IssueDiffCard from "@/components/IssueDiffCard";
import RealShot from "@/components/RealShot";
import AppGraph from "@/components/AppGraph";
import {
  ArrowUpRight, Eye, FileText, Activity, AlertTriangle, AlertOctagon,
  MousePointerClick, Smartphone, Gauge, Sparkles, GitCompare, Accessibility, Mic, CheckCircle2, FlaskConical,
} from "lucide-react";

const PHASE_ICONS = {
  analyze: Sparkles, explore: MousePointerClick, mobile: Smartphone,
  accessibility: Accessibility, personas: Eye, issues: AlertTriangle,
  test_cases: FlaskConical, benchmark: Gauge, report: FileText,
};
const SEV_COLOR = { critical: "#FF3B30", high: "#FF3B30", medium: "#FF9500", low: "#86868B" };

function MockBrowser({ url, action, target, viewport }) {
  return (
    <div className="rounded-xl bg-white border border-black/10 overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-black/5 bg-[#F5F5F7]">
        <span className="w-2 h-2 rounded-full bg-[#FF3B30]/70" />
        <span className="w-2 h-2 rounded-full bg-[#FF9500]/70" />
        <span className="w-2 h-2 rounded-full bg-[#34C759]/70" />
        <div className="flex-1 mx-3 px-3 py-1 rounded-md bg-white border border-black/5 text-[11px] text-[#86868B] truncate font-mono">
          {url}
        </div>
        <span className="text-[10px] uppercase tracking-[0.2em] text-[#86868B]">{viewport || "Desktop"}</span>
      </div>
      <div className="relative aspect-[16/10] bg-gradient-to-br from-[#F5F5F7] via-white to-[#EEF3FA]">
        <div className="absolute inset-0 dot-grid opacity-50" />
        <div className="absolute top-6 left-6 right-6 h-8 rounded-md bg-white shadow-sm border border-black/5" />
        <div className="absolute top-20 left-6 w-2/3 h-3 rounded bg-[#1D1D1F]/80" />
        <div className="absolute top-28 left-6 w-1/2 h-2 rounded bg-[#86868B]/50" />
        <div className="absolute top-36 left-6 right-6 grid grid-cols-3 gap-3">
          <div className="aspect-square rounded-xl bg-white border border-black/5 shadow-sm" />
          <div className="aspect-square rounded-xl bg-white border border-black/5 shadow-sm" />
          <div className="aspect-square rounded-xl bg-white border border-black/5 shadow-sm" />
        </div>
        <div className="absolute bottom-6 left-6 right-6 flex items-center justify-between">
          <div className="h-9 w-28 rounded-full bg-[#0071E3]" />
          <div className="h-9 w-20 rounded-full bg-[#1D1D1F]/10" />
        </div>
        {action && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="rounded-full bg-[#1D1D1F] text-white text-xs px-3 py-1.5 shadow-lg flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-[#FF3B30] live-dot" />
              {action} → {target}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ScoreRing({ value, label, color = "#0071E3" }) {
  const v = Math.max(0, Math.min(100, value || 0));
  const c = 2 * Math.PI * 36;
  const offset = c - (c * v) / 100;
  return (
    <div className="flex flex-col items-center" data-testid={`score-ring-${label.toLowerCase()}`}>
      <svg width="92" height="92" viewBox="0 0 92 92">
        <circle cx="46" cy="46" r="36" stroke="#EFEFF4" strokeWidth="8" fill="none" />
        <circle
          cx="46" cy="46" r="36" stroke={color} strokeWidth="8" fill="none"
          strokeDasharray={c} strokeDashoffset={offset} strokeLinecap="round"
          transform="rotate(-90 46 46)"
        />
        <text x="46" y="52" textAnchor="middle" className="font-display" fontSize="22" fill="#1D1D1F" fontWeight="500">
          {v}
        </text>
      </svg>
      <div className="mt-2 text-[10px] uppercase tracking-[0.2em] text-[#86868B]">{label}</div>
    </div>
  );
}

export default function RunMonitor() {
  const { runId } = useParams();
  const navigate = useNavigate();

  const [run, setRun] = useState(null);
  const [project, setProject] = useState(null);
  const [events, setEvents] = useState([]);
  const [done, setDone] = useState(false);
  const feedRef = useRef(null);

  // Hydrate from API once
  useEffect(() => {
    getRun(runId).then((r) => {
      setRun(r.data.run);
      setProject(r.data.project);
      setEvents(r.data.events || []);
      if (r.data.run?.status === "completed" || r.data.run?.status === "failed") {
        setDone(true);
      }
    }).catch(() => navigate("/dashboard", { replace: true }));
  }, [runId, navigate]);

  // SSE
  useEffect(() => {
    const es = new EventSource(`${BACKEND_URL}/api/runs/${runId}/stream`, { withCredentials: true });
    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        setEvents((prev) => {
          if (prev.some((p) => p.seq === data.seq)) return prev;
          return [...prev, data].sort((a, b) => a.seq - b.seq);
        });
      } catch {
        /* ignore malformed event */
      }
    };
    es.addEventListener("done", () => {
      setDone(true);
      getRun(runId).then((r) => setRun(r.data.run)).catch(() => {});
      es.close();
    });
    es.onerror = () => { es.close(); };
    return () => es.close();
  }, [runId]);

  // Auto-scroll log
  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight;
  }, [events]);

  const logs = events.filter((e) => e.kind === "log");
  const phases = events.filter((e) => e.kind === "phase");
  const screenshots = events.filter((e) => e.kind === "screenshot");
  const viewports = events.filter((e) => e.kind === "viewport");
  const personas = events.filter((e) => e.kind === "persona");
  const issues = events.filter((e) => e.kind === "issue");
  const benchmarks = events.filter((e) => e.kind === "benchmark");
  const summary = events.find((e) => e.kind === "summary");
  const focusEv = events.find((e) => e.kind === "plan");
  const focusAreas = focusEv?.focus_areas || [];

  // Fold app_graph + page_capture events into a list of discovered pages.
  const appPages = useMemo(() => {
    // Start from the latest app_graph event (it has the canonical page list).
    const graphEv = [...events].reverse().find((e) => e.kind === "app_graph");
    const base = (graphEv?.pages || []).map((p) => ({
      url: p.url, title: p.title, slug: p.slug, captures: {},
    }));
    const byUrl = new Map(base.map((p) => [p.url, p]));
    for (const ev of events) {
      if (ev.kind === "page_capture") {
        let entry = byUrl.get(ev.url);
        if (!entry) {
          entry = { url: ev.url, title: ev.title || "", slug: `page${ev.page_index ?? byUrl.size}`, captures: {} };
          byUrl.set(ev.url, entry);
        }
        entry.captures[ev.viewport] = { ok: ev.ok, url_path: ev.url_path };
        if (ev.title && !entry.title) entry.title = ev.title;
      }
    }
    return Array.from(byUrl.values());
  }, [events]);

  // Fold test_case + test_case_step events into a stateful map.
  const { testCases, stepIndex, activeRunningId } = useMemo(() => {
    const tcs = new Map();
    const steps = {};
    let active = null;
    for (const ev of events) {
      if (ev.kind === "test_case") {
        const existing = tcs.get(ev.id) || {};
        tcs.set(ev.id, { ...existing, ...ev });
        if (ev.status === "running") active = ev.id;
      } else if (ev.kind === "test_case_step") {
        steps[ev.case_id] = ev.step_index;
      }
    }
    return { testCases: Array.from(tcs.values()), stepIndex: steps, activeRunningId: active };
  }, [events]);

  const [activeTab, setActiveTab] = useState("live");
  const [selectedCaseId, setSelectedCaseId] = useState(null);
  const [issuePageFilter, setIssuePageFilter] = useState(null);

  // Auto-switch focus: when test_cases phase begins, prefer that tab; auto-select the running case.
  useEffect(() => {
    if (testCases.length > 0 && activeTab === "live" && !done) {
      setActiveTab("cases");
    }
  }, [testCases.length, activeTab, done]);
  useEffect(() => {
    if (activeRunningId) setSelectedCaseId(activeRunningId);
    else if (!selectedCaseId && testCases.length > 0) setSelectedCaseId(testCases[0].id);
  }, [activeRunningId, testCases, selectedCaseId]);

  const selectedCase = testCases.find((tc) => tc.id === selectedCaseId);

  const latestShot = screenshots[screenshots.length - 1];
  const currentPhase = phases[phases.length - 1];

  const progress = useMemo(() => {
    const total = 9; // analyze, explore, mobile, a11y, personas, issues, test_cases, benchmark, report
    const seen = new Set(phases.map((p) => p.phase));
    return Math.round((seen.size / total) * 100);
  }, [phases]);

  if (!run) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <AtmosMark size={32} pulse />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#F5F5F7]" data-testid="run-monitor-page">
      <SiteHeader />
      <main className="max-w-7xl mx-auto px-4 md:px-6 py-6 md:py-8 grid lg:grid-cols-12 gap-4 md:gap-6">
        {/* HEADER ROW */}
        <div className="lg:col-span-12 card-elev p-5 md:p-6 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <Badge variant="outline" className="rounded-full font-mono text-[11px] border-black/15" data-testid="run-command-badge">
                {run.command}
              </Badge>
              <div className="flex items-center gap-2 text-sm">
                {done ? (
                  run.status === "completed" ? (
                    <><CheckCircle2 className="h-4 w-4 text-[#34C759]" /> <span>Completed</span></>
                  ) : (
                    <><AlertOctagon className="h-4 w-4 text-[#FF3B30]" /> <span>Failed</span></>
                  )
                ) : (
                  <><span className="w-1.5 h-1.5 rounded-full bg-[#FF3B30] live-dot" /> <span>Live</span></>
                )}
              </div>
            </div>
            <h1 className="mt-3 font-display text-2xl md:text-3xl tracking-tight font-medium">
              {project?.name}
              <a href={project?.url} target="_blank" rel="noreferrer" className="ml-3 inline-block text-[#86868B] hover:text-[#0071E3]" data-testid="project-url-link">
                <ArrowUpRight className="h-4 w-4 inline" />
              </a>
            </h1>
            <div className="text-sm text-[#86868B] mt-1">{project?.url} · archetype: {project?.app_type}</div>
          </div>

          <div className="flex items-center gap-6">
            <div className="text-right">
              <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B]">Progress</div>
              <div className="font-display text-3xl tabular-nums">{progress}%</div>
            </div>
            {done && summary && (
              <Link to={`/runs/${runId}/report`}>
                <Button className="rounded-full bg-[#1D1D1F] hover:bg-black text-white h-11 px-5" data-testid="view-report-button">
                  View report <FileText className="ml-2 h-4 w-4" />
                </Button>
              </Link>
            )}
          </div>
        </div>

        {/* LEFT: tabbed view — live capture / test cases (with playback) / issues with diffs */}
        <section className="lg:col-span-8 space-y-4 md:space-y-6">
          <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
            <TabsList className="bg-white border border-black/10 rounded-full h-11 p-1" data-testid="run-tabs">
              <TabsTrigger value="live" className="rounded-full data-[state=active]:bg-[#1D1D1F] data-[state=active]:text-white px-4" data-testid="tab-live">
                Live capture
              </TabsTrigger>
              <TabsTrigger value="cases" className="rounded-full data-[state=active]:bg-[#1D1D1F] data-[state=active]:text-white px-4" data-testid="tab-cases">
                Test cases {testCases.length > 0 && <span className="ml-1.5 text-xs opacity-70">({testCases.length})</span>}
              </TabsTrigger>
              <TabsTrigger value="issues" className="rounded-full data-[state=active]:bg-[#1D1D1F] data-[state=active]:text-white px-4" data-testid="tab-issues">
                Issues {issues.length > 0 && <span className="ml-1.5 text-xs opacity-70">({issues.length})</span>}
              </TabsTrigger>
            </TabsList>

            {/* LIVE */}
            <TabsContent value="live" className="space-y-4 md:space-y-6 mt-4">
              <div className="card-elev p-4 md:p-5" data-testid="cinematic-panel">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2 text-xs text-[#86868B] uppercase tracking-[0.2em]">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#FF3B30] live-dot" />
                    Cinematic capture · your app
                  </div>
                  {currentPhase && (
                    <div className="text-xs text-[#86868B]">{currentPhase.label}</div>
                  )}
                </div>
                {latestShot?.url_path ? (
                  <RealShot
                    urlPath={latestShot.url_path}
                    label={`${latestShot.viewport} · ${project?.url}`}
                    badge="captured"
                    testid="cinematic-real-shot"
                  />
                ) : (
                  <MockBrowser
                    url={project?.url}
                    action={latestShot?.action}
                    target={latestShot?.target}
                    viewport={latestShot?.viewport}
                  />
                )}
                {screenshots.length > 0 && (
                  <div className="mt-4 grid grid-cols-4 gap-2">
                    {screenshots.slice(-4).map((s) => (
                      s.url_path ? (
                        <RealShot
                          key={s.seq}
                          urlPath={s.url_path}
                          label={s.viewport}
                          aspect="4/3"
                        />
                      ) : (
                        <div key={s.seq} className="rounded-md aspect-video bg-gradient-to-br from-[#F5F5F7] to-white border border-black/5 relative overflow-hidden">
                          <div className="absolute inset-0 dot-grid opacity-50" />
                          <div className="absolute bottom-1 left-1 right-1 text-[9px] font-mono text-[#1D1D1F]/70 truncate">{s.action} {s.target}</div>
                        </div>
                      )
                    ))}
                  </div>
                )}
              </div>

              <div className="terminal p-4 md:p-5" data-testid="activity-feed">
                <div className="flex items-center justify-between text-[10px] uppercase tracking-[0.2em] text-white/40 mb-3">
                  <span>Activity feed</span>
                  <span>{events.length} events</span>
                </div>
                <ScrollArea className="h-72 scrollbar-thin">
                  <div ref={feedRef} className="space-y-1 pr-2">
                    {logs.map((l) => (
                      <div key={l.seq} className="flex gap-3 anim-slide-up">
                        <span className="text-white/30 tabular-nums shrink-0">{new Date(l.ts).toLocaleTimeString([], { hour12: false })}</span>
                        <span className="text-white/85 break-words">{l.message}</span>
                      </div>
                    ))}
                    {phases.map((p) => (
                      <div key={`p-${p.seq}`} className="flex gap-3 anim-slide-up">
                        <span className="text-white/30 tabular-nums shrink-0">{new Date(p.ts).toLocaleTimeString([], { hour12: false })}</span>
                        <span className="text-[#0A84FF]">▸ {p.label}</span>
                      </div>
                    ))}
                    {issues.map((i) => (
                      <div key={`i-${i.seq}`} className="flex gap-3 anim-slide-up">
                        <span className="text-white/30 tabular-nums shrink-0">{new Date(i.ts).toLocaleTimeString([], { hour12: false })}</span>
                        <span style={{ color: SEV_COLOR[i.severity] || "#fff" }}>
                          {i.severity}  {i.title} <span className="text-white/40">— {i.file}</span>
                        </span>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              </div>
            </TabsContent>

            {/* TEST CASES */}
            <TabsContent value="cases" className="grid md:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] gap-4 mt-4" data-testid="tab-cases-content">
              <TestCaseList
                cases={testCases}
                activeId={selectedCaseId}
                onSelect={setSelectedCaseId}
                currentSteps={stepIndex}
              />
              <TestCaseTheatre
                testCase={selectedCase}
                currentStep={selectedCase ? (stepIndex[selectedCase.id] ?? (selectedCase.status !== "running" ? (selectedCase.steps?.length ?? 0) - 1 : -1)) : -1}
              />
            </TabsContent>

            {/* ISSUES (diff cards) — optionally filtered by selected page */}
            <TabsContent value="issues" className="space-y-4 mt-4" data-testid="tab-issues-content">
              {appPages.length > 1 && (
                <div className="card-elev p-3 flex items-center gap-2 flex-wrap" data-testid="issue-page-filter">
                  <span className="text-[10px] uppercase tracking-[0.18em] text-[#86868B] mr-1">Filter by page</span>
                  <button
                    type="button"
                    onClick={() => setIssuePageFilter(null)}
                    className={`text-xs rounded-full px-3 py-1 ${issuePageFilter === null ? "bg-[#1D1D1F] text-white" : "bg-white border border-black/10"}`}
                    data-testid="issue-filter-all"
                  >
                    All ({issues.length})
                  </button>
                  {appPages.map((p) => {
                    const n = issues.filter((i) => i.page_url === p.url).length;
                    if (n === 0) return null;
                    return (
                      <button
                        key={p.url}
                        type="button"
                        onClick={() => setIssuePageFilter(p.url)}
                        className={`text-xs rounded-full px-3 py-1 truncate max-w-[260px] ${issuePageFilter === p.url ? "bg-[#1D1D1F] text-white" : "bg-white border border-black/10"}`}
                        data-testid={`issue-filter-${p.slug}`}
                      >
                        {p.title || p.url} <span className="opacity-60 ml-1">({n})</span>
                      </button>
                    );
                  })}
                </div>
              )}
              {issues.length === 0 ? (
                <div className="card-elev p-10 text-center text-sm text-[#86868B]">Atmos hasn&apos;t surfaced issues yet — they appear here with before / after diffs.</div>
              ) : (
                issues
                  .filter((iss) => !issuePageFilter || iss.page_url === issuePageFilter)
                  .map((iss) => <IssueDiffCard key={iss.id} issue={iss} />)
              )}
            </TabsContent>
          </Tabs>
        </section>

        {/* RIGHT */}
        <aside className="lg:col-span-4 space-y-4 md:space-y-6">
          {/* Application graph */}
          <AppGraph pages={appPages} onSelect={(url) => { setIssuePageFilter(url); setActiveTab("issues"); }} selectedUrl={issuePageFilter} />

          {/* Phases */}
          <div className="card-elev p-5">
            <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-4">Phases</div>
            <div className="space-y-2">
              {["analyze", "explore", "mobile", "accessibility", "personas", "issues", "test_cases", "benchmark", "report"].map((ph) => {
                const reached = phases.some((p) => p.phase === ph);
                const Icon = PHASE_ICONS[ph] || Activity;
                return (
                  <div
                    key={ph}
                    className={`flex items-center gap-3 rounded-lg px-3 py-2 ${reached ? "bg-[#F5F5F7]" : ""}`}
                    data-testid={`phase-row-${ph}`}
                  >
                    <Icon className={`h-4 w-4 ${reached ? "text-[#0071E3]" : "text-[#A1A1A6]"}`} strokeWidth={1.5} />
                    <span className={`text-sm capitalize ${reached ? "text-[#1D1D1F]" : "text-[#A1A1A6]"}`}>
                      {ph}
                    </span>
                    {reached && <span className="ml-auto text-[10px] text-[#34C759]">●</span>}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Focus areas */}
          {focusAreas.length > 0 && (
            <div className="card-elev p-5" data-testid="focus-areas-card">
              <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-3">Focus areas</div>
              <div className="flex flex-wrap gap-2">
                {focusAreas.map((f, i) => (
                  <span key={i} className="text-xs rounded-full bg-[#F5F5F7] px-3 py-1.5 text-[#1D1D1F]/80">{f}</span>
                ))}
              </div>
            </div>
          )}

          {/* Viewports */}
          {viewports.length > 0 && (
            <div className="card-elev p-5" data-testid="viewports-card">
              <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-3">Responsive sweep</div>
              <div className="space-y-2">
                {viewports.map((v) => (
                  <div key={v.seq} className="flex items-center justify-between text-sm">
                    <span>{v.viewport}</span>
                    <span className="font-mono text-xs text-[#86868B]">{v.w}×{v.h}</span>
                    <span className={`text-xs ${v.status === "warn" ? "text-[#FF9500]" : "text-[#34C759]"}`}>{v.status}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Personas */}
          {personas.length > 0 && (
            <div className="card-elev p-5" data-testid="personas-card">
              <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-3">Persona simulation</div>
              <div className="space-y-2">
                {personas.map((p) => (
                  <div key={p.seq} className="flex items-center justify-between">
                    <div className="text-sm">{p.label}</div>
                    <div className="font-display tabular-nums text-base">
                      <span style={{ color: p.score >= 80 ? "#34C759" : p.score >= 65 ? "#FF9500" : "#FF3B30" }}>
                        {p.score}
                      </span>
                      <span className="text-[#A1A1A6] text-xs ml-0.5">/100</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Live scores */}
          {summary && (
            <div className="card-elev p-5" data-testid="live-scores-card">
              <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-3">Final scores</div>
              <div className="grid grid-cols-3 gap-2">
                <ScoreRing value={summary.scores?.accessibility} label="A11y" color="#0071E3" />
                <ScoreRing value={summary.scores?.ux} label="UX" color="#34C759" />
                <ScoreRing value={summary.scores?.reliability} label="Reliab." color="#FF9500" />
              </div>
            </div>
          )}

          {/* Issue list snapshot */}
          {issues.length > 0 && (
            <div className="card-elev p-5" data-testid="issues-snapshot">
              <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-3">Issues ({issues.length})</div>
              <div className="space-y-3">
                {issues.slice(-5).map((i) => (
                  <div key={i.seq} className="flex gap-3">
                    <span className="mt-1 w-1.5 h-1.5 rounded-full shrink-0" style={{ background: SEV_COLOR[i.severity] || "#86868B" }} />
                    <div className="text-sm">
                      <div className="font-medium leading-snug">{i.title}</div>
                      <div className="font-mono text-[11px] text-[#86868B] mt-0.5">{i.file}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Benchmarks */}
          {benchmarks.length > 0 && (
            <div className="card-elev p-5" data-testid="benchmarks-card">
              <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-3">Benchmark</div>
              <div className="space-y-3">
                {benchmarks.map((b) => (
                  <div key={b.seq} className="flex items-center justify-between text-sm">
                    <div>{b.competitor}</div>
                    <div className="font-mono text-xs">
                      <span className="text-[#FF3B30]">{b.your_clicks}</span>
                      <span className="text-[#86868B]"> vs </span>
                      <span className="text-[#34C759]">{b.clicks_to_primary}</span>
                      <span className="text-[#86868B]"> clicks</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </aside>
      </main>
    </div>
  );
}
