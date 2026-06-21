import { ScenePlayer } from "@/components/Scene";
import RealShot from "@/components/RealShot";
import { CheckCircle2, AlertTriangle, AlertOctagon, Clock } from "lucide-react";

const STATUS_META = {
  running: { color: "#FF9500", Icon: Clock, label: "Running" },
  pass: { color: "#34C759", Icon: CheckCircle2, label: "Passed" },
  warn: { color: "#FF9500", Icon: AlertTriangle, label: "Warning" },
  fail: { color: "#FF3B30", Icon: AlertOctagon, label: "Failed" },
};

export function TestCaseList({ cases = [], activeId, onSelect, currentSteps = {} }) {
  return (
    <div className="card-elev p-5" data-testid="test-cases-list">
      <div className="flex items-center justify-between mb-4">
        <div className="text-[10px] uppercase tracking-[0.18em] text-[#86868B]">Live test cases</div>
        <div className="text-xs text-[#86868B] tabular-nums">{cases.length} total</div>
      </div>
      <div className="space-y-1.5">
        {cases.map((tc) => {
          const meta = STATUS_META[tc.status] || STATUS_META.running;
          const isActive = activeId === tc.id;
          const stepIdx = currentSteps[tc.id] ?? -1;
          return (
            <button
              key={tc.id}
              type="button"
              onClick={() => onSelect?.(tc.id)}
              className={`w-full text-left rounded-xl px-3 py-2.5 border transition flex items-start gap-3 active:scale-[0.99] ${isActive ? "border-[#0071E3] bg-[#F5FAFF]" : "border-black/5 bg-white hover:border-black/15"}`}
              data-testid={`test-case-row-${tc.id}`}
            >
              <meta.Icon
                className={`h-4 w-4 mt-0.5 shrink-0 ${tc.status === "running" ? "live-dot" : ""}`}
                style={{ color: meta.color }}
                strokeWidth={1.75}
              />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium leading-snug">{tc.name}</div>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-[10px] uppercase tracking-[0.18em] text-[#86868B]">{tc.category}</span>
                  {tc.status === "running" && (
                    <span className="text-[10px] text-[#86868B]">step {Math.max(0, stepIdx + 1)}/{tc.steps?.length || 0}</span>
                  )}
                </div>
              </div>
              <span className="text-[10px] uppercase tracking-[0.18em]" style={{ color: meta.color }}>
                {meta.label}
              </span>
            </button>
          );
        })}
        {cases.length === 0 && (
          <div className="text-sm text-[#86868B] py-6 text-center">Waiting for Atmos to start the test cases…</div>
        )}
      </div>
    </div>
  );
}

export function TestCaseTheatre({ testCase, currentStep }) {
  if (!testCase) {
    return (
      <div className="card-elev p-6 h-full flex items-center justify-center text-sm text-[#86868B]" data-testid="test-case-theatre-empty">
        Select a test case to watch Atmos perform it.
      </div>
    );
  }
  const meta = STATUS_META[testCase.status] || STATUS_META.running;
  return (
    <div className="card-elev p-5 md:p-6" data-testid={`test-case-theatre-${testCase.id}`}>
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <div className="text-[10px] uppercase tracking-[0.18em] text-[#86868B]">{testCase.category}</div>
          <div className="font-display text-xl font-medium leading-snug mt-1">{testCase.name}</div>
        </div>
        <span className="text-[10px] uppercase tracking-[0.18em] rounded-full px-2 py-1" style={{ background: `${meta.color}1A`, color: meta.color }}>
          {meta.label}
        </span>
      </div>

      {testCase.frames && testCase.frames.length > 0 ? (
        <RealShot
          urlPath={testCase.frames[Math.min(Math.max(0, currentStep), testCase.frames.length - 1)]}
          label={`step ${Math.min(currentStep + 1, (testCase.steps || []).length)}/${(testCase.steps || []).length}`}
          badge={testCase.status === "running" ? "rec · live" : meta.label.toLowerCase()}
          tone={testCase.status === "pass" ? "ok" : testCase.status === "fail" ? "broken" : testCase.status === "warn" ? "warn" : "ok"}
        />
      ) : testCase.scene ? (
        <ScenePlayer
          scene={testCase.scene}
          steps={testCase.steps || []}
          currentStep={currentStep}
          status={testCase.status}
        />
      ) : (
        <RealShot urlPath={null} label="No frames captured" badge="unavailable" tone="warn" />
      )}

      <ol className="mt-5 space-y-2">
        {(testCase.steps || []).map((s, i) => {
          const done = i < currentStep || testCase.status !== "running";
          const active = i === currentStep && testCase.status === "running";
          return (
            <li key={i} className="flex items-start gap-3 text-sm" data-testid={`test-step-${testCase.id}-${i}`}>
              <span className={`mt-1.5 w-1.5 h-1.5 rounded-full shrink-0 ${active ? "bg-[#FF3B30] live-dot" : done ? "bg-[#34C759]" : "bg-[#A1A1A6]"}`} />
              <span className={`${active ? "text-[#1D1D1F] font-medium" : done ? "text-[#1D1D1F]/85" : "text-[#A1A1A6]"}`}>{s}</span>
            </li>
          );
        })}
      </ol>

      {testCase.status !== "running" && testCase.explanation && (
        <div className="mt-5 rounded-xl bg-[#F5F5F7] p-4 text-sm text-[#1D1D1F]/85" data-testid={`test-explanation-${testCase.id}`}>
          <div className="text-[10px] uppercase tracking-[0.18em] text-[#86868B] mb-1">Verdict</div>
          {testCase.explanation}
        </div>
      )}
    </div>
  );
}
