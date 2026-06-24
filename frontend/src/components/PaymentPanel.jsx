import { useState } from "react";
import { simulatePayments } from "@/lib/api";
import { toast } from "sonner";
import { CreditCard, ShieldAlert, ShieldCheck, Layers, Zap } from "lucide-react";

const PROVIDERS = [
  { id: "stripe", label: "Stripe" },
  { id: "razorpay", label: "Razorpay" },
  { id: "paypal", label: "PayPal" },
];

const ALL_OUTCOMES = [
  { id: "success", label: "Success", color: "#34C759" },
  { id: "decline_insufficient_funds", label: "Decline · NSF", color: "#FF9500" },
  { id: "decline_lost_card", label: "Decline · Lost card", color: "#FF9500" },
  { id: "decline_expired_card", label: "Decline · Expired", color: "#FF9500" },
  { id: "fraud", label: "Fraud", color: "#FF3B30" },
  { id: "3ds_required", label: "3DS required", color: "#0071E3" },
  { id: "network_timeout", label: "Network timeout", color: "#86868B" },
];

const CONCURRENT_PRESETS = [10, 25, 50, 100, 200];

function Tile({ label, value, color = "#1D1D1F", testId }) {
  return (
    <div className="rounded-2xl bg-[#F5F5F7] p-5" data-testid={testId}>
      <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B]">{label}</div>
      <div className="font-display text-4xl tabular-nums mt-1" style={{ color }}>{value}</div>
    </div>
  );
}

export default function PaymentPanel({ runId }) {
  const [provider, setProvider] = useState("stripe");
  const [concurrent, setConcurrent] = useState(25);
  const [amountUsd, setAmountUsd] = useState(49.99);
  const [outcomes, setOutcomes] = useState(["success", "decline_insufficient_funds", "fraud", "3ds_required"]);
  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState(null);
  const [results, setResults] = useState([]);

  const toggleOutcome = (id) => {
    setOutcomes((prev) => prev.includes(id) ? prev.filter((o) => o !== id) : [...prev, id]);
  };

  const handleRun = async () => {
    if (outcomes.length === 0) {
      toast.error("Pick at least one outcome to simulate.");
      return;
    }
    setBusy(true);
    setSummary(null); setResults([]);
    try {
      const r = await simulatePayments(runId, {
        provider,
        concurrent,
        outcomes,
        amount_cents: Math.round(amountUsd * 100),
      });
      setSummary(r.data.summary);
      setResults(r.data.results || []);
      toast.success(`${r.data.summary.success_count}/${r.data.summary.concurrent} payments settled`);
    } catch (e) {
      toast.error("Payment simulation failed", { description: e?.response?.data?.detail || e.message });
    } finally {
      setBusy(false);
    }
  };

  const successRate = summary?.success_rate != null ? (summary.success_rate * 100) : null;
  const byOutcome = summary?.by_outcome || {};

  return (
    <div className="space-y-4" data-testid="payment-panel">
      {/* Hero / config */}
      <div className="card-elev p-6 md:p-8" data-testid="payment-config">
        <div className="flex items-start gap-4">
          <div className="h-12 w-12 rounded-2xl bg-[#1D1D1F] flex items-center justify-center shrink-0">
            <CreditCard className="h-6 w-6 text-white" strokeWidth={1.5} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B]">Finance & payments sandbox</div>
            <div className="font-display text-2xl md:text-3xl mt-1">Stress every payment edge case at once.</div>
            <div className="text-sm text-[#86868B] mt-2">
              Atmos fires N concurrent payment intents through Stripe / Razorpay / PayPal test cards covering
              success, declines, fraud and 3DS — then reports settlement latency and pass-through.
            </div>
          </div>
        </div>

        <div className="mt-6 space-y-5">
          {/* Provider */}
          <div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-2">Provider</div>
            <div className="grid grid-cols-3 gap-2">
              {PROVIDERS.map((p) => {
                const active = provider === p.id;
                return (
                  <button
                    key={p.id}
                    onClick={() => setProvider(p.id)}
                    data-testid={`pay-provider-${p.id}`}
                    className={`rounded-xl p-3 border transition-colors ${
                      active ? "border-[#0071E3] bg-[#F0F7FF]" : "border-black/10 bg-white hover:border-black/20"
                    }`}
                  >
                    <div className="font-medium text-sm">{p.label}</div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Concurrent */}
          <div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-2">Concurrent attempts</div>
            <div className="flex flex-wrap gap-2">
              {CONCURRENT_PRESETS.map((n) => (
                <button
                  key={n}
                  onClick={() => setConcurrent(n)}
                  data-testid={`pay-concurrent-${n}`}
                  className={`rounded-full px-4 h-9 text-sm tabular-nums ${
                    concurrent === n ? "bg-[#1D1D1F] text-white" : "bg-[#F5F5F7] text-[#1D1D1F] hover:bg-[#EDEDF0]"
                  }`}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>

          {/* Amount */}
          <div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-2">Amount (USD)</div>
            <div className="flex items-center gap-2">
              <span className="text-[#86868B]">$</span>
              <input
                type="number" min={0.5} step={0.01} value={amountUsd}
                onChange={(e) => setAmountUsd(parseFloat(e.target.value) || 0)}
                className="w-32 h-10 rounded-md border border-black/10 px-3 text-sm tabular-nums"
                data-testid="pay-amount"
              />
            </div>
          </div>

          {/* Outcomes */}
          <div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-2">
              Outcomes to fuzz {outcomes.length === 0 && <span className="text-[#FF3B30] normal-case tracking-normal ml-1">· pick at least one</span>}
            </div>
            <div className="flex flex-wrap gap-2">
              {ALL_OUTCOMES.map((o) => {
                const active = outcomes.includes(o.id);
                return (
                  <button
                    key={o.id}
                    onClick={() => toggleOutcome(o.id)}
                    data-testid={`pay-outcome-${o.id}`}
                    className={`rounded-full px-3 h-8 text-xs border transition-colors ${
                      active ? "border-transparent text-white" : "border-black/10 text-[#1D1D1F] bg-white hover:border-black/20"
                    }`}
                    style={active ? { background: o.color } : undefined}
                  >
                    {o.label}
                  </button>
                );
              })}
            </div>
          </div>

          <button
            onClick={handleRun}
            disabled={busy}
            data-testid="payment-start"
            className="w-full md:w-auto rounded-full h-11 px-6 bg-[#1D1D1F] text-white text-sm font-medium disabled:opacity-50 inline-flex items-center gap-2"
          >
            <Zap className="h-4 w-4" strokeWidth={2} />
            {busy ? "Running…" : `Run ${concurrent} concurrent ${provider} payments`}
          </button>
        </div>
      </div>

      {/* Summary */}
      {summary && (
        <div className="card-elev p-6" data-testid="payment-summary">
          <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-3 flex items-center gap-2">
            {summary.success_rate >= 0.95 ? <ShieldCheck className="h-3 w-3 text-[#34C759]" /> : <ShieldAlert className="h-3 w-3 text-[#FF9500]" />}
            {summary.provider} · {summary.concurrent} attempts
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Tile
              label="Success"
              value={`${summary.success_count}`}
              color={successRate > 95 ? "#34C759" : successRate > 80 ? "#FF9500" : "#FF3B30"}
              testId="pay-tile-success"
            />
            <Tile
              label="Declined"
              value={`${summary.decline_count}`}
              color={summary.decline_count === 0 ? "#34C759" : "#FF9500"}
              testId="pay-tile-decline"
            />
            <Tile label="P50 latency" value={`${summary.p50_latency_ms}ms`} testId="pay-tile-p50" />
            <Tile label="P95 latency" value={`${summary.p95_latency_ms}ms`} testId="pay-tile-p95" />
          </div>

          {/* By outcome */}
          {Object.keys(byOutcome).length > 0 && (
            <div className="mt-5">
              <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-2">By outcome</div>
              <div className="flex flex-wrap gap-2">
                {Object.entries(byOutcome).map(([k, v]) => {
                  const def = ALL_OUTCOMES.find((o) => o.id === k);
                  return (
                    <div key={k} className="rounded-full bg-white border border-black/10 px-3 h-8 text-xs flex items-center gap-2">
                      <span className="w-1.5 h-1.5 rounded-full" style={{ background: def?.color || "#86868B" }} />
                      {def?.label || k} · <span className="tabular-nums font-medium">{v}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Results table */}
      {results.length > 0 && (
        <div className="card-elev p-6" data-testid="payment-results-table">
          <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B] mb-3 flex items-center gap-2">
            <Layers className="h-3 w-3" /> Per-attempt outcomes
          </div>
          <div className="rounded-xl border border-black/5 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-[#F5F5F7] text-[#86868B]">
                <tr>
                  <th className="text-left px-3 py-2 font-normal text-[11px] uppercase tracking-wider">#</th>
                  <th className="text-left px-3 py-2 font-normal text-[11px] uppercase tracking-wider">Card</th>
                  <th className="text-left px-3 py-2 font-normal text-[11px] uppercase tracking-wider">Outcome</th>
                  <th className="text-left px-3 py-2 font-normal text-[11px] uppercase tracking-wider">Result</th>
                  <th className="text-right px-3 py-2 font-normal text-[11px] uppercase tracking-wider">Latency</th>
                </tr>
              </thead>
              <tbody className="font-mono text-[12px]">
                {results.slice(0, 50).map((r) => {
                  const def = ALL_OUTCOMES.find((o) => o.id === r.outcome);
                  return (
                    <tr key={r.idx} className="border-t border-black/5">
                      <td className="px-3 py-1.5 text-[#86868B]">{r.idx}</td>
                      <td className="px-3 py-1.5">•••• {r.test_card || "----"}</td>
                      <td className="px-3 py-1.5">
                        <span className="inline-flex items-center gap-1.5">
                          <span className="w-1.5 h-1.5 rounded-full" style={{ background: def?.color || "#86868B" }} />
                          {def?.label || r.outcome}
                        </span>
                      </td>
                      <td className="px-3 py-1.5">
                        <span style={{ color: r.result === "success" ? "#34C759" : "#FF3B30" }}>{r.result}</span>
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{r.latency_ms}ms</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {results.length > 50 && (
              <div className="text-xs text-[#86868B] text-center py-2 bg-[#F5F5F7]">
                Showing 50 of {results.length} attempts
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
