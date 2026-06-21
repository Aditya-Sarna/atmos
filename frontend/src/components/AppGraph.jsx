/**
 * AppGraph — the list of pages Atmos discovered while crawling.
 * Each row shows the URL, title, and per-viewport capture status with a thumbnail.
 */
import { Globe, CheckCircle2, AlertOctagon } from "lucide-react";
import RealShot from "@/components/RealShot";

export default function AppGraph({ pages = [], onSelect, selectedUrl }) {
  if (!pages || pages.length === 0) {
    return (
      <div className="card-elev p-5 text-sm text-[#86868B]" data-testid="app-graph-empty">
        Atmos is still discovering pages…
      </div>
    );
  }
  return (
    <div className="card-elev p-5" data-testid="app-graph">
      <div className="flex items-center justify-between mb-4">
        <div className="text-[10px] uppercase tracking-[0.18em] text-[#86868B] flex items-center gap-2">
          <Globe className="h-3.5 w-3.5" strokeWidth={1.75} /> Application graph
        </div>
        <div className="text-xs text-[#86868B] tabular-nums">{pages.length} page{pages.length === 1 ? "" : "s"}</div>
      </div>

      <div className="space-y-3">
        {pages.map((p) => {
          const desktop = p.captures?.["Desktop 1440"];
          const mobile = p.captures?.["iPhone SE"];
          const isSelected = selectedUrl === p.url;
          return (
            <button
              key={p.url}
              type="button"
              onClick={() => onSelect?.(p.url)}
              className={`w-full text-left rounded-2xl border transition active:scale-[0.997] ${isSelected ? "border-[#0071E3] bg-[#F5FAFF]" : "border-black/5 bg-white hover:border-black/15"}`}
              data-testid={`app-graph-row-${p.slug || p.url}`}
            >
              <div className="p-3 flex items-start gap-3">
                <div className="w-20 shrink-0">
                  {desktop?.url_path ? (
                    <RealShot
                      urlPath={desktop.url_path}
                      label="desktop"
                      fit="cover"
                      aspect="16/10"
                    />
                  ) : (
                    <div className="aspect-[16/10] rounded-md bg-[#F5F5F7] border border-black/5" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-sm leading-snug truncate">{p.title || p.url}</div>
                  <div className="font-mono text-[11px] text-[#86868B] truncate">{p.url}</div>
                  <div className="mt-1.5 flex items-center gap-3 text-[11px]">
                    <span className="flex items-center gap-1" data-testid={`graph-status-desktop-${p.slug || p.url}`}>
                      {desktop?.ok ? (
                        <CheckCircle2 className="h-3 w-3 text-[#34C759]" strokeWidth={1.75} />
                      ) : (
                        <AlertOctagon className="h-3 w-3 text-[#FF3B30]" strokeWidth={1.75} />
                      )}
                      Desktop
                    </span>
                    <span className="flex items-center gap-1" data-testid={`graph-status-mobile-${p.slug || p.url}`}>
                      {mobile?.ok ? (
                        <CheckCircle2 className="h-3 w-3 text-[#34C759]" strokeWidth={1.75} />
                      ) : (
                        <AlertOctagon className="h-3 w-3 text-[#FF3B30]" strokeWidth={1.75} />
                      )}
                      iPhone SE
                    </span>
                  </div>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
