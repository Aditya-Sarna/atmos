/**
 * RealShot — renders a real (potentially full-page tall) screenshot.
 *
 * Behaviour:
 *   - `fit="full"` (default) → the entire image is visible at its natural
 *     aspect ratio. The container caps height with `maxHeight` and becomes
 *     vertically scrollable, so tall pages show the whole thing while staying
 *     within the card. `object-position: top` keeps the head of the page in
 *     view.
 *   - `fit="cover"` → the image is cropped to a fixed aspect (used for tiny
 *     thumbnails in the cinematic strip).
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
  fit = "full",
  maxHeight = 520,
  aspect = "16/10",
  testid,
}) {
  const src = resolveSrc(urlPath);
  const [loaded, setLoaded] = useState(false);
  const [errored, setErrored] = useState(false);
  const toneColor = tone === "broken" ? "#FF3B30" : tone === "warn" ? "#FF9500" : "#34C759";

  const isFull = fit === "full";

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

      {isFull ? (
        <div
          className="relative bg-[#F5F5F7] overflow-y-auto scrollbar-thin"
          style={{ maxHeight: `${maxHeight}px` }}
        >
          {!src || errored ? (
            <div className="flex items-center justify-center text-[#86868B] gap-2 text-xs py-12">
              <ImageOff className="h-4 w-4" strokeWidth={1.5} /> screenshot unavailable
            </div>
          ) : (
            <>
              {!loaded && (
                <div className="absolute inset-0 dot-grid opacity-40 pointer-events-none" />
              )}
              <img
                src={src}
                alt={label || "screenshot"}
                loading="lazy"
                onLoad={() => setLoaded(true)}
                onError={() => setErrored(true)}
                className={`w-full h-auto block transition-opacity duration-300 ${loaded ? "opacity-100" : "opacity-0"}`}
                data-testid={testid ? `${testid}-img` : undefined}
              />
            </>
          )}
        </div>
      ) : (
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
                data-testid={testid ? `${testid}-img` : undefined}
              />
            </>
          )}
        </div>
      )}
    </div>
  );
}
