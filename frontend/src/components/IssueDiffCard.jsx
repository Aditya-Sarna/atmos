import { useState } from "react";
import Scene from "@/components/Scene";
import RealShot from "@/components/RealShot";
import { ArrowRight, Sparkles, GitBranch, FileCode2, CheckCircle2, AlertTriangle } from "lucide-react";
import { applyPatch, BACKEND_URL } from "@/lib/api";
import { toast } from "sonner";

const SEV_COLOR = { critical: "#FF3B30", high: "#FF3B30", medium: "#FF9500", low: "#86868B" };

/**
 * IssueDiffCard — visual diff of a single problem on the user's own app.
 *
 * Renders REAL screenshots when the issue carries `before.screenshot_url` /
 * `after.screenshot_url` (produced by the Playwright + Claude vision engine),
 * and falls back to a CSS-only Scene illustration when those are missing
 * (e.g. site blocked the bot or engine ran in demo mode).
 */
export default function IssueDiffCard({ issue, runId }) {
  const [altIndex, setAltIndex] = useState(-1);
  const alt = altIndex >= 0 ? issue.alternatives?.[altIndex] : null;
  const [busy, setBusy] = useState(null); // "issue" | `alt-${i}`
  const [pr, setPr] = useState(null);

  const hasRealBefore = !!issue.before?.screenshot_url;
  const hasRealAfter = !!issue.after?.screenshot_url;
  const diffUrl = issue.after?.diff_url;
  const changedPct = issue.after?.changed_pct;
  const noOp = issue.after?.applied === false;

  const apply = async (body, key) => {
    if (!runId) {
      toast.error("Run id missing", { description: "Reload the run page and try again." });
      return;
    }
    setBusy(key);
    try {
      const r = await applyPatch(runId, body);
      setPr({ url: r.data.url, number: r.data.number });
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
    <div className="card-elev p-5 md:p-6 anim-slide-up" data-testid={`issue-diff-${issue.id}`}>
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-3 text-[10px] uppercase tracking-[0.18em]">
            <span className="text-[#86868B]">{issue.category}</span>
            <span className="font-medium" style={{ color: SEV_COLOR[issue.severity] || "#86868B" }}>{issue.severity}</span>
            {issue.viewport && (
              <span className="text-[#86868B]">· {issue.viewport}</span>
            )}
          </div>
          <div className="font-display text-xl md:text-2xl font-medium mt-1 leading-snug">{issue.title}</div>
          {issue.page_url && (
            <div className="font-mono text-xs text-[#0071E3] mt-1 truncate" data-testid={`issue-page-url-${issue.id}`}>
              {issue.page_title ? `${issue.page_title} · ` : ""}{issue.page_url}
            </div>
          )}
          {issue.file && (
            <div className="font-mono text-xs text-[#86868B] mt-1 flex items-center gap-1.5">
              <FileCode2 className="h-3.5 w-3.5" strokeWidth={1.5} /> {issue.file}
            </div>
          )}
          {issue.cause && <div className="text-sm text-[#1D1D1F]/70 mt-2">Likely cause: {issue.cause}</div>}
        </div>
        {/* Tick-to-apply on the primary fix */}
        <div className="flex flex-col items-end gap-1 shrink-0">
          <button
            type="button"
            onClick={() => apply({ kind: "issue", issue_id: issue.id }, "issue")}
            disabled={busy === "issue" || !!pr}
            className="rounded-full h-9 px-4 inline-flex items-center gap-1.5 bg-[#1D1D1F] text-white text-xs disabled:opacity-60"
            data-testid={`issue-apply-${issue.id}`}
            title="Open a PR with this fix"
          >
            <CheckCircle2 className="h-4 w-4" strokeWidth={2} />
            {pr ? `PR #${pr.number}` : busy === "issue" ? "Opening PR…" : "Apply via PR"}
          </button>
          {pr && (
            <a
              href={pr.url}
              target="_blank"
              rel="noreferrer"
              className="text-[10px] text-[#0071E3] underline"
            >
              view PR
            </a>
          )}
        </div>
      </div>

      {/* No-op warning when the engine couldn't actually apply the patch */}
      {noOp && (
        <div className="mt-4 rounded-xl border border-[#FF9500]/40 bg-[#FFF8EC] p-3 flex gap-2 text-xs text-[#7a4a00]" data-testid={`issue-noop-${issue.id}`}>
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5 text-[#FF9500]" strokeWidth={1.75} />
          <div>
            <div className="font-medium">Patch didn’t change the live page.</div>
            <div className="opacity-80">{issue.after?.no_op_reason || "The selector didn’t match any element on the rendered page."} The “After” shot is overlaid with a diagnostic banner so it’s visibly different.</div>
          </div>
        </div>
      )}

      {/* Before / After diff */}
      <div className="mt-5 grid md:grid-cols-2 gap-4">
        <div>
          <div className="text-[10px] uppercase tracking-[0.18em] text-[#86868B] mb-2 flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-[#FF3B30]" /> Before · your app
          </div>
          {hasRealBefore ? (
            <RealShot
              urlPath={issue.before.screenshot_url}
              label={issue.viewport || "Before"}
              badge="captured"
              tone="broken"
              testid={`real-before-${issue.id}`}
            />
          ) : (
            <Scene scene={issue.scene} variant="before" />
          )}
          {issue.before && (
            <div className="mt-3">
              {issue.before.headline && <div className="font-medium text-sm">{issue.before.headline}</div>}
              {issue.before.detail && <div className="text-xs text-[#1D1D1F]/70 mt-1">{issue.before.detail}</div>}
            </div>
          )}
        </div>

        <div>
          <div className="text-[10px] uppercase tracking-[0.18em] text-[#86868B] mb-2 flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-[#34C759]" />
            After · <Sparkles className="h-3 w-3" strokeWidth={1.75} /> Atmos applied
          </div>
          {hasRealAfter ? (
            <RealShot
              urlPath={issue.after.screenshot_url}
              label={issue.viewport || "After"}
              badge="patched"
              tone="ok"
              testid={`real-after-${issue.id}`}
            />
          ) : (
            <Scene scene={issue.scene} variant="after" />
          )}
          {issue.after && (
            <div className="mt-3">
              {issue.after.headline && <div className="font-medium text-sm">{issue.after.headline}</div>}
              {issue.after.detail && <div className="text-xs text-[#1D1D1F]/70 mt-1">{issue.after.detail}</div>}
              {issue.after.code && (
                <pre className="terminal mt-3 px-3 py-2 text-[11px] whitespace-pre-wrap break-words">{issue.after.code}</pre>
              )}
            </div>
          )}
          {/* Pixel diff overlay — makes “identical-looking” patches obvious */}
          {diffUrl && (
            <div className="mt-3" data-testid={`issue-diff-overlay-${issue.id}`}>
              <div className="text-[10px] uppercase tracking-[0.18em] text-[#86868B] mb-1 flex items-center justify-between">
                <span>Pixel diff</span>
                {typeof changedPct === "number" && (
                  <span className={`tabular-nums ${changedPct < 0.5 ? "text-[#FF9500]" : "text-[#34C759]"}`}>
                    {changedPct.toFixed(2)}% changed
                  </span>
                )}
              </div>
              <img
                src={diffUrl.startsWith("http") ? diffUrl : `${BACKEND_URL}${diffUrl}`}
                alt="Before vs after pixel diff"
                className="w-full rounded-lg border border-black/10 block"
              />
            </div>
          )}
        </div>
      </div>

      {/* Alternatives */}
      {issue.alternatives?.length > 0 && (
        <div className="mt-6 border-t border-black/5 pt-5" data-testid={`alternatives-${issue.id}`}>
          <div className="flex items-center justify-between mb-3">
            <div className="text-[10px] uppercase tracking-[0.18em] text-[#86868B] flex items-center gap-2">
              <GitBranch className="h-3.5 w-3.5" strokeWidth={1.75} /> Alternative fixes
            </div>
            <div className="text-xs text-[#86868B]">Tap to preview the executed result on your app.</div>
          </div>

          <div className="grid sm:grid-cols-2 gap-3">
            {issue.alternatives.map((a, i) => {
              const active = altIndex === i;
              const altKey = `alt-${i}`;
              return (
                <div
                  key={i}
                  className={`rounded-2xl border p-4 transition ${active ? "border-[#0071E3] bg-[#F5FAFF]" : "border-black/10 bg-white"}`}
                  data-testid={`alternative-${issue.id}-${i}`}
                >
                  <button
                    type="button"
                    onClick={() => setAltIndex(active ? -1 : i)}
                    className="text-left w-full"
                  >
                    <div className="font-display text-base font-medium">{a.label}</div>
                    <div className="text-xs text-[#1D1D1F]/70 mt-1 leading-snug">{a.summary}</div>
                    {a.tradeoff && <div className="text-[11px] text-[#86868B] mt-2">Trade-off: {a.tradeoff}</div>}
                    {typeof a.changed_pct === "number" && (
                      <div className="text-[10px] text-[#86868B] mt-1 tabular-nums">{a.changed_pct.toFixed(2)}% pixel change</div>
                    )}
                  </button>
                  <div className="flex items-center justify-between gap-2 mt-3">
                    <span className="text-[11px] text-[#0071E3] flex items-center gap-1">
                      {active ? "Hide preview" : "Preview on your app"}
                      <ArrowRight className="h-3 w-3" />
                    </span>
                    <button
                      type="button"
                      onClick={() => apply({ kind: "alt", issue_id: issue.id, alt_index: i }, altKey)}
                      disabled={busy === altKey}
                      className="rounded-full h-8 px-3 inline-flex items-center gap-1.5 bg-white border border-black/10 text-[11px] hover:border-black/30 disabled:opacity-60"
                      data-testid={`alt-apply-${issue.id}-${i}`}
                      title="Open a PR with this alternative"
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" strokeWidth={2} />
                      {busy === altKey ? "Opening PR…" : "Apply"}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>

          {alt && (
            <div className="mt-5 grid md:grid-cols-[1fr_auto_1fr] items-center gap-4 anim-slide-up">
              {hasRealAfter ? (
                <RealShot urlPath={issue.after.screenshot_url} label="Atmos fix" badge="executed" />
              ) : (
                <Scene scene={issue.scene} variant="after" />
              )}
              <ArrowRight className="hidden md:block h-5 w-5 text-[#86868B] mx-auto" />
              {alt.screenshot_url ? (
                <RealShot urlPath={alt.screenshot_url} label={alt.label} badge="alternative" tone="warn" />
              ) : (
                <Scene scene={issue.scene} variant={alt.scene_variant || "after"} />
              )}
            </div>
          )}

          {alt?.patch_css && (
            <pre className="terminal mt-4 px-3 py-2 text-[11px] whitespace-pre-wrap break-words" data-testid={`alt-code-${issue.id}-${altIndex}`}>{alt.patch_css}</pre>
          )}
        </div>
      )}
    </div>
  );
}
