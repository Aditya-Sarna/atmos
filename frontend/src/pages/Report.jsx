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

        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-3">Craft report</div>
            <h1 className="font-display text-4xl md:text-5xl lg:text-6xl tracking-tighter font-medium leading-[1.05]">
              {project?.name}
            </h1>
            <div className="mt-2 text-[#86868B] font-mono text-sm">{run.command} · {project?.url}</div>
          </div>
          <div className="flex items-start gap-3">
            {s.craft_score?.overall != null && (
              <div className="card-elev p-5 min-w-[180px]" data-testid="craft-score-hero">
                <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B]">Craft Score</div>
                <div className="mt-1 font-display text-5xl tabular-nums tracking-tight" style={{ color: SCORE_COLOR(s.craft_score.overall) }}>
                  {s.craft_score.overall}
                </div>
                <div className="text-sm text-[#86868B] mt-1">
                  {String(s.craft_score.tier || "").replace("_", " ")} · gate {s.craft_gate?.passed ? "PASS" : "FAIL"}
                </div>
                {s.craft_baseline?.has_baseline && (
                  <div className={`mt-2 text-sm ${(s.craft_baseline.delta ?? 0) >= 0 ? "text-[#34C759]" : "text-[#FF3B30]"}`}>
                    {(s.craft_baseline.delta ?? 0) >= 0 ? "+" : ""}{s.craft_baseline.delta} vs baseline
                  </div>
                )}
              </div>
            )}
            <Button
              onClick={() => window.print()}
              variant="outline"
              className="rounded-full"
              data-testid="export-button"
            >
              <FileText className="h-4 w-4 mr-2" /> Export
            </Button>
          </div>
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

        {s.craft_score?.components && (
          <div className="mt-8 grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3" data-testid="craft-components">
            {Object.entries(s.craft_score.components).map(([k, v]) => (
              <div key={k} className="rounded-2xl bg-white border border-black/5 p-4">
                <div className="text-[10px] uppercase tracking-[0.15em] text-[#86868B]">{k}</div>
                <div className="font-display text-2xl tabular-nums mt-1" style={{ color: v != null ? SCORE_COLOR(v) : "#86868B" }}>
                  {v ?? "—"}
                </div>
                {s.craft_baseline?.component_deltas?.[k] != null && (
                  <div className="text-[11px] text-[#86868B] mt-1">
                    Δ {s.craft_baseline.component_deltas[k] >= 0 ? "+" : ""}{s.craft_baseline.component_deltas[k]}
                  </div>
                )}
              </div>
            ))}
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

        {/* Accessibility audit */}
        {s.accessibility_audit?.summary && (
          <div className="mt-10 card-elev p-6" data-testid="report-a11y">
            <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-2">Accessibility audit</div>
            <h2 className="font-display text-2xl tracking-tight font-medium mb-3">Measured checks, not theater</h2>
            <p className="text-sm leading-relaxed mb-4">{s.accessibility_audit.summary}</p>
            <div className="grid sm:grid-cols-2 gap-3">
              {(s.accessibility_audit.findings || []).slice(0, 8).map((f, i) => (
                <div key={i} className="rounded-xl border border-black/5 bg-[#F5F5F7] p-3 text-sm">
                  <div className="font-medium">{f.title}</div>
                  <div className="text-[#86868B] mt-1 text-xs">{f.cause}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Funnel */}
        {s.funnel?.comparison && (
          <div className="mt-10 card-elev p-6" data-testid="report-funnel">
            <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-2">Conversion funnel</div>
            <h2 className="font-display text-2xl tracking-tight font-medium mb-3">Path to goal</h2>
            <p className="text-sm">{s.funnel.comparison}</p>
            <div className="mt-3 flex gap-6 text-sm">
              <div><span className="text-[#86868B]">Your clicks</span> <span className="font-display text-xl ml-2">{s.funnel.your_clicks ?? "—"}</span></div>
              <div><span className="text-[#86868B]">Industry avg</span> <span className="font-display text-xl ml-2">{s.funnel.industry_avg ?? "—"}</span></div>
            </div>
            {s.funnel.video_url && (
              <video className="mt-4 w-full rounded-xl border border-black/5" src={s.funnel.video_url} controls playsInline />
            )}
          </div>
        )}

        {/* Design theory */}
        {s.design_theory?.score != null && (
          <div className="mt-10 card-elev p-6" data-testid="report-design">
            <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-2">Design theory</div>
            <h2 className="font-display text-2xl tracking-tight font-medium mb-2">
              {s.design_theory.theme_label || "Theme"} · {s.design_theory.score}/100
            </h2>
            <p className="text-sm text-[#86868B] mb-3">{s.design_theory.issue_count || 0} fundamentals issue(s)</p>
            <div className="space-y-2">
              {(s.design_theory.issues || s.design_theory.findings || []).slice(0, 6).map((d, i) => (
                <div key={i} className="text-sm border-b border-black/5 pb-2">
                  <span className="font-medium">{d.title || d.name || d.check}</span>
                  <span className="text-[#86868B]"> — {d.detail || d.recommendation || d.message}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Competitive diffs */}
        {Array.isArray(s.competitive_diffs) && s.competitive_diffs.length > 0 && (
          <div className="mt-10" data-testid="report-competitive">
            <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-2">Competitive UX</div>
            <h2 className="font-display text-2xl tracking-tight font-medium mb-5">Side-by-side vs peers</h2>
            <div className="grid md:grid-cols-2 gap-4">
              {s.competitive_diffs.slice(0, 4).map((c, i) => (
                <div key={i} className="card-elev p-4">
                  <div className="text-sm font-medium mb-2">{c.competitor || c.name || `Peer ${i + 1}`}</div>
                  <div className="grid grid-cols-2 gap-2">
                    {c.your_url || c.yours ? <img alt="yours" className="rounded-lg border border-black/5" src={c.your_url || c.yours} /> : null}
                    {c.their_url || c.theirs ? <img alt="peer" className="rounded-lg border border-black/5" src={c.their_url || c.theirs} /> : null}
                  </div>
                  {c.insight && <p className="text-xs text-[#86868B] mt-2">{c.insight}</p>}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Copywriting */}
        {s.copywriting?.alternatives?.length > 0 && (
          <div className="mt-10 card-elev p-6" data-testid="report-copy">
            <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-2">Copywriting</div>
            <h2 className="font-display text-2xl tracking-tight font-medium mb-3">Marketing alternatives</h2>
            <p className="text-sm text-[#86868B] mb-4">{s.copywriting.summary}</p>
            <div className="space-y-3">
              {s.copywriting.alternatives.slice(0, 6).map((a, i) => (
                <div key={i} className="rounded-xl bg-[#F5F5F7] p-3 text-sm">
                  <div className="text-[10px] uppercase tracking-wider text-[#86868B]">{a.profile || a.role || "alt"}</div>
                  <div className="mt-1">{a.text || a.alternative || a.copy}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Demand intelligence */}
        {(s.demand_intelligence?.executive_summary || s.demand_intelligence?.top_gaps?.length > 0) && (
          <div className="mt-10 card-elev p-6" data-testid="report-demand">
            <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-2">Demand intelligence</div>
            <h2 className="font-display text-2xl tracking-tight font-medium mb-3">What the market is asking for</h2>
            <p className="text-sm leading-relaxed mb-4">{s.demand_intelligence.executive_summary}</p>
            {(s.demand_intelligence.proposed_features || []).slice(0, 3).map((f) => (
              <div key={f.slug || f.title} className="mb-3 rounded-xl border border-black/5 p-4">
                <div className="flex justify-between gap-2">
                  <span className="font-medium">{f.title}</span>
                  <span className="text-[10px] uppercase tracking-wider text-[#FF9500]">Tier {f.tier}</span>
                </div>
              </div>
            ))}
            {(s.demand_intelligence.top_gaps || []).slice(0, 5).map((g, i) => (
              <div key={i} className="text-sm border-b border-black/5 py-2 flex justify-between">
                <span>{g.feature || g.label}</span>
                <span className="text-[#86868B] font-mono text-xs">Tier {g.tier} · {g.mentions}</span>
              </div>
            ))}
          </div>
        )}

        {/* Dopamine + dark patterns */}
        {(s.dopamine?.dark_patterns?.length > 0
          || s.dopamine?.dark_pattern_suggestions?.length > 0
          || s.dopamine?.suggestions?.length > 0) && (
          <div className="mt-10" data-testid="report-dopamine">
            <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-2">Engagement & dark patterns</div>
            <h2 className="font-display text-2xl tracking-tight font-medium mb-2">
              Dark-pattern score {s.dopamine.dark_pattern_score ?? "—"}/100
              {s.dopamine.verdict && (
                <span className="text-base text-[#86868B] font-normal ml-2">· {s.dopamine.verdict}</span>
              )}
            </h2>
            <p className="text-sm text-[#86868B] mb-4">{s.dopamine.thesis_summary}</p>

            {s.dopamine.dark_pattern_suggestions?.length > 0 && (
              <div className="card-elev p-5 mb-4 border border-[#FF3B30]/20" data-testid="report-dark-suggestions">
                <div className="rounded-xl bg-[#FFF5F5] border border-[#FF3B30]/15 p-3 mb-4 text-sm text-[#1D1D1F]/85">
                  {s.dopamine.disclaimer || "DISCLAIMER: Missing dark-pattern suggestions are for awareness / ethics review only. Do not ship them."}
                </div>
                <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-3">
                  Missing dark patterns — awareness only
                </div>
                <div className="space-y-3">
                  {s.dopamine.dark_pattern_suggestions.slice(0, 8).map((d, i) => (
                    <div key={d.id || i} className="border-b border-black/5 pb-3 last:border-0">
                      <div className="font-medium text-sm">{d.name}</div>
                      <div className="text-xs text-[#86868B] mt-0.5">missing · {d.category}</div>
                      <p className="text-sm mt-1">{d.how}</p>
                      <p className="text-xs text-[#FF3B30] mt-1">Risk: {d.risk}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {s.dopamine.dark_patterns?.length > 0 && (
              <div className="card-elev p-5 mb-4">
                <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-3">Detected on page</div>
                <div className="space-y-3">
                  {s.dopamine.dark_patterns.slice(0, 10).map((d, i) => (
                    <div key={d.id || i} className="border-b border-black/5 pb-3 last:border-0">
                      <div className="font-medium text-sm">{d.name}</div>
                      <div className="text-xs text-[#86868B] mt-0.5">{d.severity} · {d.category}</div>
                      <p className="text-sm mt-1">{d.recommendation}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {s.dopamine.suggestions?.length > 0 && (
              <div className="card-elev p-5">
                <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-3">Ethical engagement</div>
                <ul className="list-disc pl-5 text-sm space-y-2">
                  {s.dopamine.suggestions.slice(0, 8).map((sug, i) => (
                    <li key={i}>{typeof sug === "string" ? sug : sug.title || sug.summary || JSON.stringify(sug)}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {s.command_profile?.label && (
          <div className="mt-8 text-center text-xs text-[#86868B]">
            Run profile: {s.command_profile.label} · phases { (s.command_profile.phases || []).join(", ") }
          </div>
        )}

        <div className="mt-10 text-center text-sm text-[#86868B]">Atmos · Executive Report</div>
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
