import { AlertTriangle, Sparkles, ShieldAlert, CheckCircle2, Flame } from "lucide-react";

const SEV = { critical: "#FF3B30", high: "#FF3B30", medium: "#FF9500", low: "#86868B" };
const VERDICT = {
  clean: { color: "#34C759", label: "Clean" },
  watch: { color: "#FF9500", label: "Watch" },
  risky: { color: "#FF9500", label: "Risky" },
  hostile: { color: "#FF3B30", label: "Hostile" },
};

export default function DopaminePanel({ analysis, fromSummary }) {
  const data = analysis || fromSummary || null;
  const darkSuggestions = data?.dark_pattern_suggestions || [];
  const hasAny =
    data?.enabled ||
    data?.dark_patterns?.length ||
    data?.suggestions?.length ||
    darkSuggestions.length;

  if (!hasAny) {
    return (
      <div className="card-elev p-10 text-center text-sm text-[#86868B]" data-testid="dopamine-empty">
        Engagement & dark-pattern map runs in the Dopamine phase. It will appear here once that phase completes
        (included in <span className="font-mono">/atmos test</span>, report, analyze, accessibility).
      </div>
    );
  }

  const score = data.dark_pattern_score ?? 100;
  const verdict = VERDICT[data.verdict] || VERDICT.watch;
  const dark = data.dark_patterns || [];
  const suggestions = data.suggestions || [];
  const guardrails = data.ethical_guardrails || [];
  const disclaimer = data.disclaimer || (
    "DISCLAIMER: Missing dark-pattern suggestions are for competitive awareness and ethics review only. "
    + "Atmos does not recommend implementing deceptive design."
  );

  return (
    <div className="space-y-4" data-testid="dopamine-panel">
      <div className="card-elev p-6 md:p-8">
        <div className="flex items-start gap-4 flex-wrap">
          <div className="h-12 w-12 rounded-2xl bg-[#1D1D1F] flex items-center justify-center shrink-0">
            <Sparkles className="h-6 w-6 text-white" strokeWidth={1.5} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B]">Engagement & dark patterns</div>
            <div className="font-display text-2xl md:text-3xl mt-1">What&apos;s present · what&apos;s missing.</div>
            <p className="text-sm text-[#86868B] mt-2 max-w-2xl">
              {data.thesis_summary || "Detects deceptive patterns on the page and lists common ones you are not using — with a hard disclaimer."}
            </p>
          </div>
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B]">Present score</div>
            <div className="font-display text-5xl tabular-nums" style={{ color: verdict.color }} data-testid="dark-pattern-score">
              {score}
            </div>
            <div className="text-sm" style={{ color: verdict.color }}>{verdict.label} (detected only)</div>
          </div>
        </div>
      </div>

      {/* Missing dark-pattern suggestions — always with disclaimer */}
      <div className="card-elev p-6 border border-[#FF3B30]/25" data-testid="dark-pattern-suggestions">
        <div className="rounded-xl bg-[#FFF5F5] border border-[#FF3B30]/20 p-4 mb-5" data-testid="dark-pattern-disclaimer">
          <div className="text-[10px] uppercase tracking-[0.2em] text-[#FF3B30] mb-2">Disclaimer</div>
          <p className="text-sm text-[#1D1D1F]/85 leading-relaxed">{disclaimer}</p>
        </div>
        <div className="flex items-center gap-2 mb-4">
          <Flame className="h-4 w-4 text-[#FF3B30]" />
          <div className="text-xs uppercase tracking-[0.2em] text-[#86868B]">
            Missing dark patterns — awareness only ({darkSuggestions.length})
          </div>
        </div>
        {darkSuggestions.length === 0 ? (
          <p className="text-sm text-[#86868B]">
            No additional catalog suggestions — the page already shows most common deceptive patterns, or scope was narrow.
          </p>
        ) : (
          <div className="grid md:grid-cols-2 gap-3">
            {darkSuggestions.map((s, i) => (
              <div key={s.id || i} className="rounded-xl border border-[#FF3B30]/15 bg-[#F5F5F7] p-4">
                <div className="font-medium text-sm">{s.name}</div>
