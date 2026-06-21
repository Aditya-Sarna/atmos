import { useState } from "react";
import Scene from "@/components/Scene";
import RealShot from "@/components/RealShot";
import { ArrowRight, Sparkles, GitBranch, FileCode2 } from "lucide-react";

const SEV_COLOR = { critical: "#FF3B30", high: "#FF3B30", medium: "#FF9500", low: "#86868B" };

/**
 * IssueDiffCard — visual diff of a single problem on the user's own app.
 *
 * Renders REAL screenshots when the issue carries `before.screenshot_url` /
 * `after.screenshot_url` (produced by the Playwright + Claude vision engine),
 * and falls back to a CSS-only Scene illustration when those are missing
 * (e.g. site blocked the bot or engine ran in demo mode).
 */
export default function IssueDiffCard({ issue }) {
  const [altIndex, setAltIndex] = useState(-1);
  const alt = altIndex >= 0 ? issue.alternatives?.[altIndex] : null;

  const hasRealBefore = !!issue.before?.screenshot_url;
  const hasRealAfter = !!issue.after?.screenshot_url;

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
          {issue.file && (
            <div className="font-mono text-xs text-[#86868B] mt-1 flex items-center gap-1.5">
              <FileCode2 className="h-3.5 w-3.5" strokeWidth={1.5} /> {issue.file}
            </div>
          )}
          {issue.cause && <div className="text-sm text-[#1D1D1F]/70 mt-2">Likely cause: {issue.cause}</div>}
        </div>
      </div>

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
              return (
                <button
                  key={i}
                  type="button"
                  onClick={() => setAltIndex(active ? -1 : i)}
                  className={`text-left rounded-2xl border p-4 transition active:scale-[0.99] ${active ? "border-[#0071E3] bg-[#F5FAFF]" : "border-black/10 bg-white hover:border-black/25"}`}
                  data-testid={`alternative-${issue.id}-${i}`}
                >
                  <div className="font-display text-base font-medium">{a.label}</div>
                  <div className="text-xs text-[#1D1D1F]/70 mt-1 leading-snug">{a.summary}</div>
                  {a.tradeoff && <div className="text-[11px] text-[#86868B] mt-2">Trade-off: {a.tradeoff}</div>}
                  <div className="mt-2 text-[11px] text-[#0071E3] flex items-center gap-1">
                    {active ? "Hide preview" : "Preview on your app"}
                    <ArrowRight className="h-3 w-3" />
                  </div>
                </button>
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
