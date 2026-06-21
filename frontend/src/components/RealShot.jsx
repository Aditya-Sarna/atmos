/**
 * RealShot — renders a real screenshot returned by the backend at /api/screens/...
 * Falls back to a soft skeleton when the path is missing or the image hasn't loaded yet.
 */
import { useState } from "react";
import { ImageOff } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";

function resolveSrc(urlPath) {
  if (!urlPath) return null;
  if (/^https?:\/\//.test(urlPath)) return urlPath;
  return `${BACKEND_URL}${urlPath}`;
}

export default function RealShot({
  urlPath,
  label,
  badge,
  tone = "ok",
  aspect = "16/10",
  testid,
}) {
  const src = resolveSrc(urlPath);
  const [loaded, setLoaded] = useState(false);
  const [errored, setErrored] = useState(false);
  const toneColor = tone === "broken" ? "#FF3B30" : tone === "warn" ? "#FF9500" : "#34C759";

  return (
    <div className="rounded-xl overflow-hidden border border-black/10 bg-white shadow-sm" data-testid={testid}>
      <div className="flex items-center justify-between px-3 py-1.5 bg-[#F5F5F7] border-b border-black/5">
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-[#FF3B30]/70" />
          <span className="w-2 h-2 rounded-full bg-[#FF9500]/70" />
          <span className="w-2 h-2 rounded-full bg-[#34C759]/70" />
        </div>
        <div className="text-[10px] uppercase tracking-[0.18em] text-[#86868B] truncate max-w-[60%]">{label}</div>
        {badge ? (
          <div className="flex items-center gap-1 text-[10px] font-medium" style={{ color: toneColor }}>
            <span className="w-1.5 h-1.5 rounded-full" style={{ background: toneColor }} />
            {badge}
          </div>
        ) : <span className="w-12" />}
      </div>
      <div style={{ aspectRatio: aspect }} className="relative overflow-hidden bg-[#F5F5F7]">
        {!src || errored ? (
          <div className="absolute inset-0 flex items-center justify-center text-[#86868B] gap-2 text-xs">
            <ImageOff className="h-4 w-4" strokeWidth={1.5} /> screenshot unavailable
          </div>
        ) : (
          <>
            {!loaded && <div className="absolute inset-0 dot-grid opacity-40" />}
            <img
              src={src}
              alt={label || "screenshot"}
              loading="lazy"
              onLoad={() => setLoaded(true)}
              onError={() => setErrored(true)}
              className={`absolute inset-0 w-full h-full object-cover object-top transition-opacity duration-300 ${loaded ? "opacity-100" : "opacity-0"}`}
            />
          </>
        )}
      </div>
    </div>
  );
}
