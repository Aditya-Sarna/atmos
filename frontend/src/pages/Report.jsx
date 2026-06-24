import { useEffect, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { getRun, applyPatch } from "@/lib/api";
import SiteHeader from "@/components/SiteHeader";
import { Button } from "@/components/ui/button";
import AtmosMark from "@/components/AtmosMark";
import IssueDiffCard from "@/components/IssueDiffCard";
import AppGraph from "@/components/AppGraph";
import { TestCaseTheatre, TestCaseList } from "@/components/TestCases";
import { ArrowLeft, FileText, AlertTriangle, Lightbulb, Sparkles, Layers, FlaskConical, CheckCircle2, Github } from "lucide-react";
import { toast } from "sonner";

const SEV_COLOR = { critical: "#FF3B30", high: "#FF3B30", medium: "#FF9500", low: "#86868B" };
const SCORE_COLOR = (v) => (v >= 80 ? "#34C759" : v >= 65 ? "#FF9500" : "#FF3B30");

function BigScore({ label, value }) {
  return (
    <div className="card-elev p-6 md:p-8 flex flex-col items-start" data-testid={`big-score-${label.toLowerCase()}`}>
      <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B]">{label}</div>
      <div className="mt-2 font-display text-5xl md:text-6xl tabular-nums tracking-tight" style={{ color: SCORE_COLOR(value) }}>
        {value}
      </div>
      <div className="text-sm text-[#86868B] mt-1">/ 100</div>
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

export default function Report() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const [run, setRun] = useState(null);
  const [project, setProject] = useState(null);

  useEffect(() => {
    getRun(runId).then((r) => {
      if (!r.data.run?.summary) {
        navigate(`/runs/${runId}`, { replace: true });
        return;
      }
      setRun(r.data.run);
      setProject(r.data.project);
    }).catch(() => navigate("/dashboard", { replace: true }));
  }, [runId, navigate]);

  if (!run) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <AtmosMark size={32} pulse />
      </div>
    );
  }

  const s = run.summary;

  return (
    <div className="min-h-screen bg-[#F5F5F7]" data-testid="report-page">
      <SiteHeader />
      <main className="max-w-7xl mx-auto px-6 md:px-8 py-10 md:py-14">
        <Link to={`/runs/${runId}`} className="inline-flex items-center text-sm text-[#86868B] hover:text-[#1D1D1F] mb-6" data-testid="back-to-monitor">
          <ArrowLeft className="h-4 w-4 mr-1" /> Back to live monitor
        </Link>

        <div className="flex items-baseline justify-between gap-4 flex-wrap">
          <div>
            <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-3">Executive report</div>
            <h1 className="font-display text-4xl md:text-5xl lg:text-6xl tracking-tighter font-medium leading-[1.05]">
              {project?.name}
            </h1>
            <div className="mt-2 text-[#86868B] font-mono text-sm">{run.command} · {project?.url}</div>
          </div>
          <Button
            onClick={() => window.print()}
            variant="outline"
            className="rounded-full"
            data-testid="export-button"
          >
            <FileText className="h-4 w-4 mr-2" /> Export
          </Button>
        </div>

        {project?.source === "github" && (
          <div className="mt-6 card-elev p-4 flex flex-col md:flex-row md:items-center justify-between gap-3" data-testid="github-pr-status">
            <div className="flex items-start gap-3 text-sm text-[#1D1D1F]/80">
              <Github className="h-4 w-4 mt-0.5 text-[#86868B]" />
              <div>
                <div className="font-medium text-[#1D1D1F]">
                  {project?.has_github_token ? "GitHub PRs are enabled for this report." : "GitHub repo connected, but PRs are not enabled yet."}
                </div>
                <div className="text-[#86868B] mt-1">
                  {project?.has_github_token
                    ? "Apply via PR uses the stored project token for this repository."
                    : "Add a GitHub token from New Run to let Atmos open PRs for these fixes."}
                </div>
              </div>
            </div>
            <Link to={`/dashboard/new?project=${project?.project_id || ""}`}>
              <Button variant="outline" className="rounded-full" data-testid="manage-github-token-button">
                {project?.has_github_token ? "Manage token" : "Enable PRs"}
              </Button>
            </Link>
          </div>
        )}

        {/* SCORES */}
        <div className="mt-10 grid md:grid-cols-3 gap-4">
          <BigScore label="Accessibility" value={s.scores?.accessibility ?? 0} />
          <BigScore label="UX" value={s.scores?.ux ?? 0} />
          <BigScore label="Reliability" value={s.scores?.reliability ?? 0} />
        </div>

        {/* COUNTS */}
        <div className="mt-4 card-elev p-6 grid grid-cols-2 md:grid-cols-5 gap-4">
          {Object.entries(s.counts || {}).map(([k, v]) => (
            <div key={k} data-testid={`count-${k}`}>
              <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B]">{k}</div>
              <div className="font-display text-3xl tabular-nums">{v}</div>
            </div>
          ))}
        </div>

        {/* CRITICAL FINDINGS + RECOMMENDATIONS */}
        <div className="mt-6 grid lg:grid-cols-2 gap-4">
          <div className="card-elev p-6 md:p-8" data-testid="critical-findings">
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-[#86868B] mb-4">
              <AlertTriangle className="h-3.5 w-3.5" strokeWidth={1.75} /> Critical findings
            </div>
            <ul className="space-y-3">
              {(s.critical_findings || []).map((c, i) => (
                <li key={i} className="flex gap-3 text-[#1D1D1F]/90">
                  <span className="mt-2 w-1.5 h-1.5 rounded-full bg-[#FF3B30] shrink-0" />
                  <span>{c}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="card-elev p-6 md:p-8" data-testid="recommendations">
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-[#86868B] mb-4">
              <Lightbulb className="h-3.5 w-3.5" strokeWidth={1.75} /> Top recommendations
            </div>
            <ol className="space-y-3 list-decimal pl-5">
              {(s.recommendations || []).map((c, i) => (
                <li key={i} className="text-[#1D1D1F]/90">{c}</li>
              ))}
            </ol>
          </div>
        </div>

        {/* COMPETITIVE INSIGHT */}
        {s.competitive_insight && (
          <div className="mt-6 card-elev p-6 md:p-8 bg-[#1D1D1F] text-white" data-testid="competitive-insight">
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-white/40 mb-3">
              <Sparkles className="h-3.5 w-3.5" /> Competitive insight
            </div>
            <p className="font-display text-xl md:text-2xl tracking-tight leading-snug">{s.competitive_insight}</p>
            <div className="mt-4 text-sm text-white/55">Benchmarked against: {(s.benchmarks || []).map((b) => b.competitor).join(" · ")}</div>
          </div>
        )}

        {/* PERSONAS */}
        <div className="mt-6 card-elev p-6 md:p-8" data-testid="report-personas">
          <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-5">Persona scores</div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {(s.personas || []).map((p) => (
              <div key={p.id} className="rounded-2xl bg-[#F5F5F7] p-4" data-testid={`persona-score-${p.id}`}>
                <div className="text-sm font-medium">{p.label}</div>
                <div className="text-xs text-[#86868B] mt-0.5 leading-snug">{p.focus}</div>
                <div className="mt-3 flex items-end gap-2">
                  <div className="font-display text-3xl tabular-nums" style={{ color: SCORE_COLOR(p.score) }}>{p.score}</div>
                  <div className="text-xs text-[#A1A1A6] mb-1">/ 100</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* APPLICATION GRAPH */}
        {Array.isArray(s.app_graph) && s.app_graph.length > 0 && (
          <div className="mt-10" data-testid="report-app-graph">
            <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-2">Application graph · pages crawled</div>
            <h2 className="font-display text-2xl md:text-3xl tracking-tight font-medium mb-5">
              Atmos analysed {s.app_graph.length} page{s.app_graph.length === 1 ? "" : "s"} across your app.
            </h2>
            <AppGraph pages={s.app_graph} />
          </div>
        )}

        {/* PAGE-BY-PAGE ANALYSIS */}
        {Array.isArray(s.page_summaries) && s.page_summaries.length > 0 && (
          <div className="mt-10" data-testid="report-page-summaries">
            <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-2">Per-screen analysis</div>
            <h2 className="font-display text-2xl md:text-3xl tracking-tight font-medium mb-5">
              What Atmos found on each page.
            </h2>
            <div className="grid gap-3 md:grid-cols-2">
              {s.page_summaries.map((p, i) => (
                <div key={`${p.url}-${i}`} className="card-elev p-4 md:p-5" data-testid={`page-summary-${i}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="font-medium truncate">{p.title || p.url}</div>
                      <div className="text-xs text-[#86868B] font-mono truncate mt-1">{p.url}</div>
                    </div>
                  </div>
                  <div className="mt-3 text-sm text-[#1D1D1F]/85 leading-relaxed">
                    {p.summary || "No page-specific summary was returned for this screen."}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ISSUES with before/after + alternatives */}
        <div className="mt-10 space-y-4" data-testid="report-issues">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-2">Issues · executed fixes · alternatives</div>
              <h2 className="font-display text-2xl md:text-3xl tracking-tight font-medium">Atmos found {(s.issues || []).length} issues and shipped a fix for each.</h2>
            </div>
          </div>
          <div className="grid gap-4">
            {(s.issues || []).map((i) => (
              <IssueDiffCard key={i.id} issue={i} runId={runId} />
            ))}
          </div>
        </div>

        {/* ARCHITECTURE — only for GitHub-connected projects */}
        {s.architecture && (
          <ArchitectureSection arch={s.architecture} runId={runId} />
        )}

        {/* FUZZ TEST RESULTS */}
        {Array.isArray(s.fuzz_cases) && s.fuzz_cases.length > 0 && (
          <FuzzReportSection cases={s.fuzz_cases} />
        )}

        {/* TEST CASES with live recording playback */}
        {Array.isArray(s.test_cases) && s.test_cases.length > 0 && (
          <div className="mt-10" data-testid="report-test-cases">
            <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-2">Test cases · recorded</div>
            <h2 className="font-display text-2xl md:text-3xl tracking-tight font-medium mb-5">
              Every case Atmos performed on your UI.
            </h2>
            <ReportTestCases cases={s.test_cases} />
          </div>
        )}

        <div className="mt-10 text-center text-sm text-[#86868B]">Atmos · Generated by Claude Sonnet 4.5 · Executive Report</div>
      </main>
    </div>
  );
}

function ReportTestCases({ cases }) {
  const [selectedId, setSelectedId] = useState(cases[0]?.id || null);
  const selected = cases.find((c) => c.id === selectedId);
  return (
    <div className="grid md:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] gap-4">
      <TestCaseList
        cases={cases}
        activeId={selectedId}
        onSelect={setSelectedId}
        currentSteps={Object.fromEntries(cases.map((c) => [c.id, (c.steps?.length || 1) - 1]))}
      />
      <TestCaseTheatre
        testCase={selected}
        currentStep={(selected?.steps?.length || 1) - 1}
      />
    </div>
  );
}

// ---------------- Architecture section ----------------
function ArchitectureSection({ arch, runId }) {
  const score = arch?.score || {};
  const axes = score?.axes || {};
  const suggestions = arch?.suggestions || [];
  const peers = arch?.peer_comparison?.peers || [];
  const nextMoves = arch?.peer_comparison?.next_3_moves || [];
  const [busy, setBusy] = useState(null);
  const [appliedIds, setAppliedIds] = useState({});

  const apply = async (s) => {
    setBusy(s.id);
    try {
      const r = await applyPatch(runId, { kind: "architecture", suggestion_id: s.id });
      setAppliedIds((m) => ({ ...m, [s.id]: { url: r.data.url, number: r.data.number } }));
      toast.success(`PR #${r.data.number} opened`, {
        description: r.data.url,
        action: { label: "Open", onClick: () => window.open(r.data.url, "_blank") },
      });
    } catch (e) {
      toast.error("Could not open PR", { description: e?.response?.data?.detail || e.message });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mt-10" data-testid="report-architecture">
      <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-2 flex items-center gap-2">
        <Layers className="h-3.5 w-3.5" strokeWidth={1.75} /> Architecture
      </div>
      <h2 className="font-display text-2xl md:text-3xl tracking-tight font-medium mb-5">
        Architecture score &middot; <span className="tabular-nums">{score.overall ?? "—"}</span>/100
      </h2>

      <div className="card-elev p-6 grid md:grid-cols-5 gap-3">
        {Object.entries(axes).map(([k, v]) => (
          <div key={k} className="rounded-xl bg-[#F5F5F7] p-3">
            <div className="text-[10px] uppercase tracking-wider text-[#86868B]">{k}</div>
            <div className="font-display text-2xl tabular-nums">{v}</div>
          </div>
        ))}
      </div>

      {peers.length > 0 && (
        <div className="mt-4 card-elev p-6">
          <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-3">How peers do it</div>
          <div className="grid md:grid-cols-2 gap-3">
            {peers.map((p, i) => (
              <div key={i} className="rounded-xl border border-black/5 p-4">
                <div className="font-medium">{p.name}</div>
                <div className="text-xs text-[#86868B] mt-1">{architectureText(p.pattern || p.score)}</div>
                <div className="text-sm mt-2">{architectureText(p.takeaway || p.detail || p.what_they_do_better || p.what_to_copy)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {suggestions.length > 0 && (
        <div className="mt-4 card-elev p-6">
          <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-3">Architecture upgrades</div>
          <div className="space-y-4">
            {suggestions.map((s) => {
              const applied = appliedIds[s.id];
              return (
                <div key={s.id} className="rounded-xl border border-black/5 p-4" data-testid={`arch-suggestion-${s.id}`}>
                  <div className="flex gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="font-medium">{s.title}</div>
                      <div className="text-sm text-[#1D1D1F]/80 mt-1">{s.summary || s.rationale}</div>
                      {(s.files || []).length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mt-2">
                          {s.files.map((f) => (
                            <span key={f} className="inline-flex items-center gap-1 rounded-md bg-[#F5F5F7] px-2 py-0.5 text-[11px] font-mono text-[#1D1D1F]/70">
                              {f}{s.file_line && s.files[0] === f ? `:${s.file_line}` : ""}
                            </span>
                          ))}
                        </div>
                      )}
                      {s.peer_comparison && (
                        <div className="text-[11px] text-[#86868B] mt-2">{s.peer_comparison}</div>
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={() => apply(s)}
                      disabled={busy === s.id || !!applied}
                      className="shrink-0 self-start rounded-full h-9 px-4 inline-flex items-center gap-1.5 bg-[#1D1D1F] text-white text-xs disabled:opacity-60"
                      data-testid={`arch-apply-${s.id}`}
                      title="Open a PR with this change"
                    >
                      <CheckCircle2 className="h-4 w-4" strokeWidth={2} />
                      {applied ? `PR #${applied.number}` : busy === s.id ? "Opening PR…" : "Apply via PR"}
                    </button>
                  </div>
                  {s.code_snippet && (
                    <details className="mt-3">
                      <summary className="text-[11px] text-[#86868B] cursor-pointer select-none">
                        View code reference{s.file_line ? ` (line ${s.file_line})` : ""}
                      </summary>
                      <pre className="mt-2 rounded-lg bg-[#1D1D1F] text-[#F5F5F7] text-[11px] p-3 overflow-x-auto whitespace-pre-wrap leading-relaxed font-mono">
                        {s.code_snippet}
                      </pre>
                    </details>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {nextMoves.length > 0 && (
        <div className="mt-4 card-elev p-6">
          <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-3">Next 3 moves</div>
          <ol className="space-y-2 list-decimal pl-5 text-sm">
            {nextMoves.map((m, i) => <li key={i}>{architectureText(m)}</li>)}
          </ol>
        </div>
      )}
    </div>
  );
}

// ---------------- Fuzz section ----------------
function FuzzReportSection({ cases }) {
  // counts
  const counts = cases.reduce(
    (acc, c) => { acc[c.status || "pending"] = (acc[c.status || "pending"] || 0) + 1; return acc; },
    {}
  );
  // group by archetype
  const groups = cases.reduce((m, c) => {
    const k = c.field_archetype || "field";
    if (!m[k]) m[k] = [];
    m[k].push(c);
    return m;
  }, {});
  const statusColor = { pass: "#34C759", fail: "#FF3B30", warn: "#FF9500", pending: "#86868B" };

  return (
    <div className="mt-10" data-testid="report-fuzz">
      <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-2 flex items-center gap-2">
        <FlaskConical className="h-3.5 w-3.5" strokeWidth={1.75} /> Fuzz test results
      </div>
      <h2 className="font-display text-2xl md:text-3xl tracking-tight font-medium mb-5">
        {cases.length} boundary inputs fired across your forms.
      </h2>
      <div className="card-elev p-4 flex flex-wrap gap-2 text-xs mb-4">
        <span className="rounded-full bg-[#34C759]/10 text-[#1E8E3E] px-3 py-1">Passed {counts.pass || 0}</span>
        <span className="rounded-full bg-[#FF3B30]/10 text-[#FF3B30] px-3 py-1">Failed {counts.fail || 0}</span>
        <span className="rounded-full bg-[#FF9500]/10 text-[#B25E00] px-3 py-1">Warn {counts.warn || 0}</span>
      </div>
      <div className="space-y-3">
        {Object.entries(groups).map(([arche, items]) => (
          <div key={arche} className="card-elev p-4 md:p-5" data-testid={`report-fuzz-${arche}`}>
            <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-3">{arche} · {items.length} cases</div>
            <div className="rounded-lg overflow-hidden border border-black/5">
              <table className="w-full text-xs">
                <tbody>
                  {items.map((c) => (
                    <tr key={c.id} className="border-t border-black/5">
                      <td className="px-3 py-2 align-top w-20">
                        <span className="text-[10px] uppercase tracking-wider" style={{ color: statusColor[c.status] || "#86868B" }}>{c.status || "…"}</span>
                      </td>
                      <td className="px-3 py-2 align-top w-32 truncate">{c.field_label || c.field_name}</td>
                      <td className="px-3 py-2 align-top w-1/3 font-mono break-all">{String(c.value ?? "").slice(0, 80) || <span className="text-[#86868B]">(empty)</span>}</td>
                      <td className="px-3 py-2 align-top text-[#1D1D1F]/80">{c.expectation || c.label}</td>
                      <td className="px-3 py-2 align-top text-[#86868B]">{c.actual || ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
