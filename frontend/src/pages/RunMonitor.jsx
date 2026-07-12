import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { getRun, BACKEND_URL, applyPatch } from "@/lib/api";
import { toast } from "sonner";
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
import ChaosLabPanel from "@/components/ChaosLabPanel";
import DopaminePanel from "@/components/DopaminePanel";
import MarkdownView from "@/components/MarkdownView";
import {
  ArrowUpRight, Eye, FileText, Activity, AlertTriangle, AlertOctagon,
  MousePointerClick, Smartphone, Gauge, Sparkles, GitCompare, Accessibility, Mic, CheckCircle2, FlaskConical,
  Github, Layers, Radio, Users, CreditCard,
} from "lucide-react";

const PHASE_ICONS = {
  analyze: Sparkles, explore: MousePointerClick, mobile: Smartphone,
  accessibility: Accessibility, personas: Eye, issues: AlertTriangle,
  test_cases: FlaskConical, benchmark: Gauge, report: FileText,
  github_boot: Github, per_page: Sparkles, fuzz: FlaskConical, architecture: Layers,
};
const SEV_COLOR = { critical: "#FF3B30", high: "#FF3B30", medium: "#FF9500", low: "#86868B" };
const SCREEN_VERDICT_COLOR = { pass: "#34C759", warn: "#FF9500", fail: "#FF3B30" };

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

function architectureText(value) {
  if (value == null) return "";
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.map(architectureText).filter(Boolean).join(" · ");
  if (typeof value === "object") {
    return [value.title, value.name, value.label, value.summary, value.detail, value.takeaway, value.what_they_do_better, value.what_to_copy, value.score]
      .filter((item) => item != null && item !== "")
      .map(String)
      .join(" · ");
  }
  return String(value);
}

export default function RunMonitor() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

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
  const personaAnnotations = events.filter((e) => e.kind === "persona_annotation");
  const funnelAnalysis = events.filter((e) => e.kind === "funnel_analysis").pop();
  const customTests = events.filter((e) => e.kind === "custom_test");
  const competitiveDiffs = events.filter((e) => e.kind === "competitive_diff");
  const designTheory = events.filter((e) => e.kind === "design_theory").pop();
  const designIssues = events.filter((e) => e.kind === "design_issue");
  const dopamineAnalysis = events.filter((e) => e.kind === "dopamine_analysis").pop();
  const testPlanEv = events.find((e) => e.kind === "test_plan");
  const copySuggestions = events.filter((e) => e.kind === "copy_suggestion");
  const copywritingReport = events.filter((e) => e.kind === "copywriting_report").pop()
    || run?.summary?.copywriting
    || null;
  const demandReport = events.filter((e) => e.kind === "demand_report").pop()
    || run?.summary?.demand_intelligence
    || null;
  const issues = events.filter((e) => e.kind === "issue");
  const benchmarks = events.filter((e) => e.kind === "benchmark");
  const summary = events.find((e) => e.kind === "summary");
  const focusEv = events.find((e) => e.kind === "plan");
  const focusAreas = focusEv?.focus_areas || [];

  // The latest live JPEG frame published by the engine (crawl, fuzz, etc.)
  const liveFrames = events.filter((e) => e.kind === "live_frame");
  const latestFrame = liveFrames[liveFrames.length - 1];
  const routeVideos = events.filter((e) => e.kind === "route_video");

  // Screens discovered by the agentic flow explorer (onboarding → hub → fan-out).
  const screensDiscovered = events.filter((e) => e.kind === "screen_discovered");

  // Per-screen test cases (each carries its own video clip), grouped by screen.
  const screenTestGroups = useMemo(() => {
    const groups = new Map();
    for (const ev of events) {
      if (ev.kind !== "screen_test") continue;
      const key = ev.screen_name || ev.screen_id || "Screen";
      if (!groups.has(key)) {
        groups.set(key, { name: key, purpose: ev.screen_purpose || "", route: ev.route, cases: [] });
      }
      const g = groups.get(key);
      if (ev.screen_purpose && !g.purpose) g.purpose = ev.screen_purpose;
      g.cases.push(ev);
    }
    return Array.from(groups.values());
  }, [events]);

  // Fuzz cases (start + end events keyed by id).
  const fuzzCases = useMemo(() => {
    const m = new Map();
    for (const ev of events) {
      if (ev.kind === "fuzz_case") {
        const prev = m.get(ev.id) || {};
        m.set(ev.id, { ...prev, ...ev });
      }
    }
    return Array.from(m.values());
  }, [events]);

  // Architecture analysis snapshot (last one wins).
  const architecture = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i--) {
      if (events[i].kind === "architecture") return events[i];
    }
    return null;
  }, [events]);

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

  const [activeTab, setActiveTab] = useState(() => searchParams.get("tab") || "live");

  useEffect(() => {
    const t = searchParams.get("tab");
    if (t) setActiveTab(t);
  }, [searchParams]);
  const [selectedCaseId, setSelectedCaseId] = useState(null);
  const [issuePageFilter, setIssuePageFilter] = useState(null);
  const [testingToken, setTestingToken] = useState(false);
  const [tokenTestResult, setTokenTestResult] = useState(null);

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
    const total = 13; // github_boot, analyze, explore, per_page, a11y, personas, issues, fuzz, screen_tests, architecture, test_cases, custom_tests, benchmark, report
    const seen = new Set(phases.map((p) => p.phase));
    return Math.min(100, Math.round((seen.size / total) * 100));
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

        {project?.source === "github" && (
          <div className="lg:col-span-12 card-elev p-4 flex flex-col md:flex-row md:items-center justify-between gap-3" data-testid="github-pr-status">
            <div className="flex items-start gap-3 text-sm text-[#1D1D1F]/80">
              <Github className="h-4 w-4 mt-0.5 text-[#86868B]" />
              <div>
                <div className="font-medium text-[#1D1D1F]">
                  {project?.has_github_token ? "GitHub PRs are enabled for this run." : "GitHub repo connected, but PRs are not enabled yet."}
                </div>
                <div className="text-[#86868B] mt-1">
                  {project?.has_github_token
                    ? "Apply via PR will use the stored project token. Use Test connection to verify it works before clicking Apply."
                    : "Add a GitHub token from New Run to let Atmos open PRs for findings."}
                </div>
                {tokenTestResult && (
                  <div
                    className={`mt-2 inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs ${
                      tokenTestResult.ok ? "bg-[#E8F8EE] text-[#34C759]" : "bg-[#FFF1F1] text-[#FF3B30]"
                    }`}
                    data-testid="github-token-test-result"
                  >
                    {tokenTestResult.ok ? <CheckCircle2 className="h-3 w-3" /> : <AlertTriangle className="h-3 w-3" />}
                    {tokenTestResult.detail}
                  </div>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2">
              {project?.has_github_token && (
                <Button
                  variant="outline"
                  className="rounded-full"
                  data-testid="test-github-token-button"
                  disabled={testingToken}
                  onClick={async () => {
                    setTestingToken(true);
                    setTokenTestResult(null);
                    try {
                      const r = await (await import("@/lib/api")).testGithubToken(project.project_id);
                      setTokenTestResult(r.data);
                      if (r.data?.ok) toast.success("GitHub token is valid", { description: `Logged in as ${r.data.login}` });
                      else toast.error("Token check failed", { description: r.data?.detail });
                    } catch (e) {
                      const detail = e?.response?.data?.detail || e.message;
                      setTokenTestResult({ ok: false, detail });
                      toast.error("Token check failed", { description: detail });
                    } finally {
                      setTestingToken(false);
                    }
                  }}
                >
                  {testingToken ? "Testing…" : "Test connection"}
                </Button>
              )}
              <Link to={`/dashboard/new?project=${project?.project_id || ""}`}>
                <Button variant="outline" className="rounded-full" data-testid="manage-github-token-button">
                  {project?.has_github_token ? "Manage token" : "Enable PRs"}
                </Button>
              </Link>
            </div>
          </div>
        )}

        {/* Capability hero */}
        <div className="lg:col-span-12 grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="capability-hero">
          {[
            { id: "live",         icon: Radio,       title: "Real testing",        sub: "Crawl · click · screenshot · LLM audit" },
            { id: "chaos",        icon: Users,       title: "Chaos Lab",           sub: "Architecture live stress · crash test" },
            { id: "architecture", icon: Layers,      title: "Architecture",        sub: "Industry-peer benchmark + auto-PR" },
            { id: "demand",       icon: CreditCard,  title: "Demand & copy",       sub: "What to build · how to say it" },
          ].map((c) => {
            const Icon = c.icon;
            const active = activeTab === c.id || (c.id === "demand" && (activeTab === "copy" || activeTab === "demand"));
            return (
              <button
                key={c.id}
                onClick={() => setActiveTab(c.id === "demand" ? "demand" : c.id)}
                data-testid={`cap-${c.id}`}
                className={`text-left rounded-2xl border p-4 transition-all ${
                  active ? "bg-[#1D1D1F] text-white border-[#1D1D1F]" : "bg-white border-black/10 hover:border-black/30"
                }`}
              >
                <Icon className={`h-5 w-5 ${active ? "text-white" : "text-[#0071E3]"}`} strokeWidth={1.5} />
                <div className={`font-medium text-sm mt-2 ${active ? "text-white" : ""}`}>{c.title}</div>
                <div className={`text-[11px] mt-0.5 ${active ? "text-white/60" : "text-[#86868B]"}`}>{c.sub}</div>
              </button>
            );
          })}
        </div>
        {/* LEFT: tabbed view — live capture / test cases (with playback) / issues with diffs */}
        <section className="lg:col-span-8 space-y-4 md:space-y-6">
          <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
            <TabsList className="bg-white border border-black/10 rounded-full h-11 p-1 flex-wrap" data-testid="run-tabs">
              <TabsTrigger value="live" className="rounded-full data-[state=active]:bg-[#1D1D1F] data-[state=active]:text-white px-4" data-testid="tab-live">
                Live capture
              </TabsTrigger>
              <TabsTrigger value="cases" className="rounded-full data-[state=active]:bg-[#1D1D1F] data-[state=active]:text-white px-4" data-testid="tab-cases">
                Test cases {testCases.length > 0 && <span className="ml-1.5 text-xs opacity-70">({testCases.length})</span>}
              </TabsTrigger>
              <TabsTrigger value="issues" className="rounded-full data-[state=active]:bg-[#1D1D1F] data-[state=active]:text-white px-4" data-testid="tab-issues">
                Issues {issues.length > 0 && <span className="ml-1.5 text-xs opacity-70">({issues.length})</span>}
              </TabsTrigger>
              <TabsTrigger value="fuzz" className="rounded-full data-[state=active]:bg-[#1D1D1F] data-[state=active]:text-white px-4" data-testid="tab-fuzz">
                Fuzz {fuzzCases.length > 0 && <span className="ml-1.5 text-xs opacity-70">({fuzzCases.length})</span>}
              </TabsTrigger>
              <TabsTrigger value="chaos" className="rounded-full data-[state=active]:bg-[#1D1D1F] data-[state=active]:text-white px-4" data-testid="tab-chaos">
                Chaos Lab
              </TabsTrigger>
              <TabsTrigger value="dopamine" className="rounded-full data-[state=active]:bg-[#1D1D1F] data-[state=active]:text-white px-4" data-testid="tab-dopamine">
                Dopamine {(dopamineAnalysis?.dark_patterns?.length > 0 || dopamineAnalysis?.suggestions?.length > 0 || summary?.dopamine?.dark_patterns?.length > 0) && (
                  <span className="ml-1.5 text-xs opacity-70">
                    ({(dopamineAnalysis?.dark_patterns?.length || summary?.dopamine?.dark_patterns?.length || 0)
                      + (dopamineAnalysis?.suggestions?.length || summary?.dopamine?.suggestions?.length || 0)})
                  </span>
                )}
              </TabsTrigger>
              <TabsTrigger value="architecture" className="rounded-full data-[state=active]:bg-[#1D1D1F] data-[state=active]:text-white px-4" data-testid="tab-architecture">
                Architecture {architecture && <span className="ml-1.5 text-xs opacity-70">{architecture?.score?.overall ?? ""}</span>}
              </TabsTrigger>
              <TabsTrigger value="copy" className="rounded-full data-[state=active]:bg-[#1D1D1F] data-[state=active]:text-white px-4" data-testid="tab-copy">
                Copy {copySuggestions.length > 0 && <span className="ml-1.5 text-xs opacity-70">({copySuggestions.length})</span>}
              </TabsTrigger>
              <TabsTrigger value="demand" className="rounded-full data-[state=active]:bg-[#1D1D1F] data-[state=active]:text-white px-4" data-testid="tab-demand">
                Demand {demandReport?.top_gaps?.length > 0 && <span className="ml-1.5 text-xs opacity-70">({demandReport.top_gaps.length})</span>}
              </TabsTrigger>
            </TabsList>

            {/* LIVE */}
            <TabsContent value="live" className="space-y-4 md:space-y-6 mt-4">
              {/* Live MJPEG-over-SSE stream — updates as Atmos crawls, clicks buttons, and fuzzes inputs */}
              {latestFrame && (
                <div className="card-elev p-4 md:p-5" data-testid="live-stream-panel">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2 text-xs text-[#86868B] uppercase tracking-[0.2em]">
                      <Radio className="h-3.5 w-3.5 text-[#FF3B30] animate-pulse" />
                      Live stream · {latestFrame.kind === "fuzz" ? "fuzz" : "exploration"}
                    </div>
                    <div className="text-xs font-mono text-[#86868B] truncate max-w-[60%]">{latestFrame.label}</div>
                  </div>
                  <div className="rounded-xl overflow-hidden border border-black/10 bg-black">
                    <img
                      src={`data:image/jpeg;base64,${latestFrame.image_b64}`}
                      alt={latestFrame.label}
                      className="w-full block"
                      data-testid="live-stream-frame"
                    />
                  </div>
                  <div className="text-[10px] text-[#86868B] mt-2">
                    {liveFrames.length} frames received · {done ? "stream ended" : "streaming"}
                  </div>
                </div>
              )}
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

              {routeVideos.length > 0 && (
                <div className="card-elev p-4 md:p-5" data-testid="route-video-panel">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2 text-xs text-[#86868B] uppercase tracking-[0.2em]">
                      Route recordings
                    </div>
                    <div className="text-xs text-[#86868B]">{routeVideos.length} clips</div>
                  </div>
                  <div className="grid md:grid-cols-2 gap-3">
                    {routeVideos.slice(-6).map((v, idx) => (
                      <div key={`${v.seq || idx}-${v.route || idx}`} className="rounded-xl border border-black/10 p-2 bg-[#F5F5F7]">
                        <div className="text-[11px] font-mono text-[#1D1D1F]/80 truncate mb-2">
                          {v.route || v.url} · {v.viewport}
                        </div>
                        <video
                          controls
                          preload="metadata"
                          className="w-full rounded-lg bg-black"
                          src={`${BACKEND_URL}${v.video_url}`}
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {screenTestGroups.length > 0 && (
                <div className="card-elev p-4 md:p-5" data-testid="screen-tests-panel">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2 text-xs text-[#86868B] uppercase tracking-[0.2em]">
                      Per-screen test cases
                    </div>
                    <div className="text-xs text-[#86868B]">
                      {screensDiscovered.length} screens ·{" "}
                      {screenTestGroups.reduce((n, g) => n + g.cases.length, 0)} cases
                    </div>
                  </div>
                  <div className="space-y-5">
                    {screenTestGroups.map((g, gi) => (
                      <div key={`scrgrp-${gi}`} className="rounded-xl border border-black/10 p-3 bg-[#F5F5F7]">
                        <div className="mb-2">
                          <div className="text-sm font-semibold text-[#1D1D1F]">{g.name}</div>
                          {g.purpose && (
                            <div className="text-xs text-[#86868B] mt-0.5">{g.purpose}</div>
                          )}
                          {g.route && (
                            <div className="text-[11px] font-mono text-[#1D1D1F]/50 mt-0.5">{g.route}</div>
                          )}
                        </div>
                        <div className="grid md:grid-cols-2 gap-3">
                          {g.cases.map((c, ci) => (
                            <div key={`scrcase-${gi}-${ci}`} className="rounded-lg border border-black/10 p-2 bg-white">
                              <div className="flex items-center justify-between mb-1">
                                <span className="text-[12px] font-medium text-[#1D1D1F] truncate pr-2">
                                  {c.case_name}
                                </span>
                                <span
                                  className="text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded shrink-0"
                                  style={{
                                    color: SCREEN_VERDICT_COLOR[c.verdict] || "#86868B",
                                    background: (SCREEN_VERDICT_COLOR[c.verdict] || "#86868B") + "1A",
                                  }}
                                >
                                  {c.verdict}
                                </span>
                              </div>
                              <div className="text-[11px] text-[#86868B] mb-1">
                                <span className="font-mono">{c.field}</span> ← “{c.value || "(empty)"}”
                                <span className="text-[#1D1D1F]/40"> · expects {c.expectation}</span>
                              </div>
                              {c.rationale && (
                                <div className="text-[11px] text-[#1D1D1F]/60 mb-2">{c.rationale}</div>
                              )}
                              {c.video_url ? (
                                <video
                                  controls
                                  preload="metadata"
                                  className="w-full rounded bg-black"
                                  src={`${BACKEND_URL}${c.video_url}`}
                                />
                              ) : c.screenshot_url ? (
                                <img
                                  alt={c.case_name}
                                  className="w-full rounded"
                                  src={`${BACKEND_URL}${c.screenshot_url}`}
                                />
                              ) : null}
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

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
                  .map((iss) => <IssueDiffCard key={iss.id} issue={iss} runId={runId} />)
              )}
            </TabsContent>

            {/* FUZZ */}
            <TabsContent value="fuzz" className="space-y-3 mt-4" data-testid="tab-fuzz-content">
              {fuzzCases.length === 0 ? (
                <div className="card-elev p-10 text-center text-sm text-[#86868B]">
                  No fuzz cases yet — Atmos starts firing boundary inputs (age=−5, dob=2026, 10k-char strings, SQL/XSS payloads, emoji bombs…) once it has finished crawling.
                </div>
              ) : (
                <FuzzCaseList cases={fuzzCases} />
              )}
            </TabsContent>

            {/* CHAOS LAB */}
            <TabsContent value="chaos" className="space-y-3 mt-4" data-testid="tab-chaos-content">
              <ChaosLabPanel
                runId={runId}
                projectId={project?.project_id}
                pages={appPages}
              />
            </TabsContent>

            {/* DOPAMINE + DARK PATTERNS */}
            <TabsContent value="dopamine" className="space-y-3 mt-4" data-testid="tab-dopamine-content">
              <DopaminePanel
                analysis={dopamineAnalysis}
                fromSummary={summary?.dopamine}
              />
            </TabsContent>

            {/* ARCHITECTURE */}
            <TabsContent value="architecture" className="space-y-3 mt-4" data-testid="tab-architecture-content">
              {!architecture ? (
                <div className="card-elev p-10 text-center text-sm text-[#86868B]">
                  Architecture analysis runs in the final phase of every test run. It will appear here once the run reaches the Architecture phase.
                </div>
              ) : (
                <ArchitecturePanel arch={architecture} runId={runId} />
              )}
            </TabsContent>

            {/* COPYWRITING */}
            <TabsContent value="copy" className="space-y-4 mt-4" data-testid="tab-copy-content">
              {(copywritingReport || copySuggestions.length > 0) ? (
                <>
                  {copywritingReport && (
                    <div className="card-elev p-5 flex items-center justify-between gap-4 flex-wrap">
                      <div>
                        <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B]">Marketing copy score</div>
                        <div className="font-display text-3xl mt-1 tabular-nums">{copywritingReport.avg_score}/100</div>
                        <p className="text-sm text-[#86868B] mt-1 max-w-xl">{copywritingReport.summary}</p>
                      </div>
                      <div className="text-xs text-[#86868B]">
                        Voice: {copywritingReport.voice?.tone || "—"}
                      </div>
                    </div>
                  )}
                  {(copySuggestions.length ? copySuggestions : copywritingReport?.suggestions || []).map((c) => (
                    <div key={c.id || c.seq} className="card-elev p-5 space-y-3" data-testid={`copy-card-${c.id || c.seq}`}>
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <span className="text-[10px] uppercase tracking-[0.18em] text-[#86868B]">{c.role}</span>
                          <div className="font-medium mt-1 text-[#1D1D1F]/50 line-through decoration-black/20">{c.original}</div>
                        </div>
                        <span className="font-display tabular-nums text-lg" style={{ color: (c.score || 0) >= 75 ? "#34C759" : (c.score || 0) >= 55 ? "#FF9500" : "#FF3B30" }}>
                          {c.score}
                        </span>
                      </div>
                      {(c.issues || []).length > 0 && (
                        <ul className="text-xs text-[#FF9500] space-y-0.5">
                          {c.issues.map((iss, i) => <li key={i}>⚠ {iss}</li>)}
                        </ul>
                      )}
                      <div className="grid sm:grid-cols-2 gap-2">
                        {(c.alternatives || []).map((alt, i) => (
                          <div key={i} className="rounded-xl border border-black/8 bg-[#F5F5F7] p-3">
                            <div className="text-[10px] uppercase tracking-wider text-[#0071E3]">{alt.profile_label || alt.profile_id}</div>
                            <div className="text-sm font-medium mt-1 leading-snug">{alt.text}</div>
                            <p className="text-[11px] text-[#86868B] mt-1">{alt.rationale}</p>
                            {alt.marketing_angle && (
                              <span className="inline-block mt-2 text-[10px] px-2 py-0.5 rounded-full bg-white border border-black/5">{alt.marketing_angle}</span>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </>
              ) : (
                <div className="card-elev p-10 text-center text-sm text-[#86868B]">
                  Marketing copy alternatives appear after Atmos extracts headlines & CTAs from your live UI.
                </div>
              )}
            </TabsContent>

            {/* DEMAND INTELLIGENCE */}
            <TabsContent value="demand" className="space-y-4 mt-4" data-testid="tab-demand-content">
              {demandReport ? (
                <>
                  <div className="card-elev p-5 space-y-3">
                    <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B]">Ecosystem demand research</div>
                    <p className="text-sm leading-relaxed">{demandReport.executive_summary}</p>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
                      {[
                        ["Reddit", demandReport.scrape_stats?.reddit_signals],
                        ["GitHub", demandReport.scrape_stats?.github_signals],
                        ["Google/Play", demandReport.scrape_stats?.google_play_signals],
                        ["Weighted", demandReport.scrape_stats?.total_weighted_mentions],
                      ].map(([label, val]) => (
                        <div key={label} className="rounded-xl bg-[#F5F5F7] p-3">
                          <div className="font-display text-xl tabular-nums">{val ?? 0}</div>
                          <div className="text-[10px] uppercase tracking-wider text-[#86868B]">{label}</div>
                        </div>
                      ))}
                    </div>
                    <div className="flex flex-wrap gap-2 text-[11px] text-[#86868B]">
                      <span>Planner: {demandReport.scrape_stats?.planner || demandReport.research_plan?.planner || "—"}</span>
                      <span>·</span>
                      <span>Synthesizer: {demandReport.scrape_stats?.synthesizer || "—"}</span>
                      <span>·</span>
                      <span>Vertical: {demandReport.vertical || demandReport.app_type}</span>
                    </div>
                  </div>

                  {(demandReport.research_plan?.keywords || []).length > 0 && (
                    <div className="card-elev p-5">
                      <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-2">Keyword research plan</div>
                      <p className="text-sm text-[#1D1D1F]/80 mb-3">{demandReport.research_plan?.domain_framing}</p>
                      {(demandReport.research_plan?.research_questions || []).length > 0 && (
                        <ol className="list-decimal pl-5 text-sm space-y-1 mb-4">
                          {demandReport.research_plan.research_questions.map((q, i) => (
                            <li key={i}>{q}</li>
                          ))}
                        </ol>
                      )}
                      <div className="overflow-x-auto">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="text-left text-[10px] uppercase tracking-wider text-[#86868B] border-b border-black/10">
                              <th className="py-2 pr-2">Query</th>
                              <th className="py-2 pr-2">Intent</th>
                              <th className="py-2">Why</th>
                            </tr>
                          </thead>
                          <tbody>
                            {demandReport.research_plan.keywords.map((k, i) => (
                              <tr key={i} className="border-b border-black/5 align-top">
                                <td className="py-2 pr-2 font-mono">{k.query}</td>
                                <td className="py-2 pr-2 whitespace-nowrap">{k.intent}</td>
                                <td className="py-2 text-[#86868B]">{k.why}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  {(demandReport.insight_docs || []).filter((d) => d.id !== "plan").map((doc) => (
                    <div key={doc.id} className="card-elev p-5">
                      <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-2">{doc.title}</div>
                      <MarkdownView markdown={doc.markdown} />
