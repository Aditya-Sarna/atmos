/**
 * Atmos Scene Renderer.
 *
 * Each issue and test case references a `scene` identifier; this component
 * paints the scene at a given `variant` ("before" | "after" | "sticky" |
 * "drawer" | "palette" | "rail" | …). All scenes are CSS-only mocks — no
 * external images — so screenshots are reproducible and lightweight.
 */
import { useEffect, useMemo, useState } from "react";

const VP = {
  mobile: { w: 280, h: 380 },
  tablet: { w: 480, h: 360 },
  desktop: { w: 560, h: 360 },
};

function Frame({ children, size = "desktop", label, badge, tone = "ok" }) {
  const dim = VP[size] || VP.desktop;
  const toneColor = tone === "broken" ? "#FF3B30" : tone === "warn" ? "#FF9500" : "#34C759";
  return (
    <div className="rounded-xl overflow-hidden border border-black/10 bg-white shadow-sm">
      <div className="flex items-center justify-between px-3 py-1.5 bg-[#F5F5F7] border-b border-black/5">
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-[#FF3B30]/70" />
          <span className="w-2 h-2 rounded-full bg-[#FF9500]/70" />
          <span className="w-2 h-2 rounded-full bg-[#34C759]/70" />
        </div>
        <div className="text-[10px] uppercase tracking-[0.18em] text-[#86868B]">{label}</div>
        {badge ? (
          <div className="flex items-center gap-1 text-[10px] font-medium" style={{ color: toneColor }}>
            <span className="w-1.5 h-1.5 rounded-full" style={{ background: toneColor }} />
            {badge}
          </div>
        ) : <span className="w-12" />}
      </div>
      <div style={{ width: "100%", aspectRatio: `${dim.w}/${dim.h}` }} className="relative overflow-hidden bg-gradient-to-br from-[#F5F5F7] via-white to-[#EEF3FA]">
        <div className="absolute inset-0 dot-grid opacity-40 pointer-events-none" />
        {children}
      </div>
    </div>
  );
}

/* ---------- Individual scenes ----------------------------------------- */

function CtaOverlap({ variant, animate }) {
  const broken = variant === "before";
  const sticky = variant === "sticky";
  const drawer = variant === "drawer";
  return (
    <Frame size="mobile" label="iPhone SE · 375×667" badge={broken ? "broken" : "fixed"} tone={broken ? "broken" : "ok"}>
      <div className="absolute top-3 left-3 right-3 h-5 rounded-md bg-white shadow-sm border border-black/5" />
      <div className="absolute top-12 left-3 right-3 h-3 rounded bg-[#1D1D1F]/70" />
      <div className="absolute top-[68px] left-3 right-3 h-2 rounded bg-[#86868B]/50" />
      <div className="absolute top-[88px] left-3 right-3 grid grid-cols-2 gap-2">
        <div className="aspect-square rounded-lg bg-white border border-black/5" />
        <div className="aspect-square rounded-lg bg-white border border-black/5" />
      </div>

      {/* CTA + footer */}
      {broken ? (
        <>
          <div className={`absolute bottom-3 left-3 h-9 w-28 rounded-full bg-[#0071E3] ${animate ? "anim-slide-up" : ""}`} />
          <div className="absolute bottom-2 left-24 right-3 h-7 rounded bg-[#1D1D1F]/15 text-[9px] text-[#1D1D1F]/65 flex items-center px-2 truncate">© 2026 · Terms · Privacy</div>
          <div className="absolute bottom-12 left-3 right-3 text-[9px] uppercase tracking-[0.18em] text-[#FF3B30] flex items-center gap-1">
            <span className="w-1 h-1 rounded-full bg-[#FF3B30]" /> overlap
          </div>
        </>
      ) : sticky ? (
        <>
          <div className="absolute bottom-0 left-0 right-0 h-12 bg-white/85 backdrop-blur border-t border-black/5 flex items-center justify-center">
            <div className="h-8 w-32 rounded-full bg-[#0071E3]" />
          </div>
          <div className="absolute bottom-14 left-3 right-3 h-5 rounded bg-[#1D1D1F]/10" />
        </>
      ) : drawer ? (
        <>
          <div className="absolute bottom-3 left-3 right-3 h-9 rounded-full bg-[#0071E3]" />
          <div className="absolute top-3 right-3 h-5 w-5 rounded bg-[#1D1D1F]/15" />
        </>
      ) : (
        <>
          <div className={`absolute bottom-14 left-3 right-3 h-9 rounded-full bg-[#0071E3] ${animate ? "anim-slide-up" : ""}`} />
          <div className="absolute bottom-3 left-3 right-3 h-5 rounded bg-[#1D1D1F]/10 text-[9px] text-[#1D1D1F]/65 flex items-center px-2 truncate">© 2026 · Terms · Privacy</div>
        </>
      )}
    </Frame>
  );
}

function AriaForm({ variant }) {
  const broken = variant === "before";
  const float = variant === "float";
  const icon = variant === "icon";
  return (
    <Frame label="Sign in" badge={broken ? "no labels" : "labeled"} tone={broken ? "broken" : "ok"}>
      <div className="absolute top-4 left-6 right-6 grid gap-3">
        <div className="text-[#1D1D1F] font-medium text-sm">Sign in</div>

        {broken ? (
          <>
            <input className="h-9 rounded-md border border-black/15 px-3 text-xs text-[#86868B] bg-white" placeholder="" />
            <input className="h-9 rounded-md border border-black/15 px-3 text-xs text-[#86868B] bg-white" placeholder="" />
            <div className="text-[9px] text-[#FF3B30] uppercase tracking-[0.18em]">screen-reader: edit, edit</div>
          </>
        ) : float ? (
          <>
            <div className="relative">
              <label className="absolute -top-1.5 left-2 bg-white px-1 text-[9px] text-[#86868B]">Email</label>
              <input className="h-9 rounded-md border border-[#0071E3] px-3 text-xs" defaultValue="ada@lovelace.dev" />
            </div>
            <div className="relative">
              <label className="absolute -top-1.5 left-2 bg-white px-1 text-[9px] text-[#86868B]">Password</label>
              <input className="h-9 rounded-md border border-black/15 px-3 text-xs" defaultValue="••••••••" />
            </div>
          </>
        ) : icon ? (
          <>
            <div className="flex items-center gap-2 h-9 rounded-md border border-black/15 px-3">
              <span className="w-3 h-3 rounded-full bg-[#1D1D1F]/40" />
              <input aria-label="Email address" className="bg-transparent text-xs flex-1" defaultValue="ada@lovelace.dev" />
            </div>
            <div className="flex items-center gap-2 h-9 rounded-md border border-black/15 px-3">
              <span className="w-3 h-3 rounded bg-[#1D1D1F]/40" />
              <input aria-label="Password" type="password" className="bg-transparent text-xs flex-1" defaultValue="secret" />
            </div>
            <div className="text-[9px] uppercase tracking-[0.18em] text-[#34C759]">aria-label set · invisible to sighted users</div>
          </>
        ) : (
          <>
            <div>
              <div className="text-[10px] text-[#86868B] mb-1">Email</div>
              <input className="h-9 rounded-md border border-black/15 px-3 text-xs w-full" defaultValue="ada@lovelace.dev" />
            </div>
            <div>
              <div className="text-[10px] text-[#86868B] mb-1">Password</div>
              <input type="password" className="h-9 rounded-md border border-black/15 px-3 text-xs w-full" defaultValue="••••••••" />
            </div>
          </>
        )}
        <div className="h-8 rounded-full bg-[#0071E3] mt-2 flex items-center justify-center text-[11px] text-white">Sign in</div>
      </div>
    </Frame>
  );
}

function DeepNav({ variant }) {
  const broken = variant === "before";
  const palette = variant === "palette";
  const rail = variant === "rail";
  const steps = broken
    ? ["☰", "Menu", "Sub", "Tab", "List", "Row", "Modal", "CTA"]
    : ["Home", "CTA"];
  return (
    <Frame label="Navigation depth" badge={broken ? "8 clicks" : "1-3 clicks"} tone={broken ? "broken" : "ok"}>
      <div className="absolute inset-0 flex items-center justify-center px-4">
        {rail ? (
          <div className="flex gap-3 w-full">
            <div className="w-12 flex flex-col gap-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className={`h-7 rounded-md ${i === 1 ? "bg-[#0071E3]" : "bg-white border border-black/10"}`} />
              ))}
            </div>
            <div className="flex-1 grid gap-2 content-start">
              <div className="h-4 w-2/3 rounded bg-[#1D1D1F]/70" />
              <div className="h-2 w-1/2 rounded bg-[#86868B]/50" />
              <div className="h-8 w-32 rounded-full bg-[#0071E3] mt-2" />
            </div>
          </div>
        ) : palette ? (
          <div className="w-72 rounded-xl border border-black/10 bg-white shadow-lg overflow-hidden">
            <div className="px-3 py-2 text-[10px] uppercase tracking-[0.18em] text-[#86868B] border-b border-black/5">⌘K · type a verb…</div>
            {["Open checkout", "Create invoice", "Start refund"].map((t, i) => (
              <div key={i} className={`px-3 py-2 text-xs ${i === 0 ? "bg-[#F5F5F7] text-[#0071E3]" : "text-[#1D1D1F]"}`}>{t}</div>
            ))}
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-1.5">
            {steps.map((s, i) => (
              <span key={i} className={`text-[10px] rounded-full px-2 py-1 ${i === steps.length - 1 ? "bg-[#0071E3] text-white" : "bg-white border border-black/10 text-[#1D1D1F]/80"}`}>
                {s}
              </span>
            ))}
          </div>
        )}
      </div>
    </Frame>
  );
}

function FocusRing({ variant }) {
  const broken = variant === "before";
  return (
    <Frame label="Keyboard focus" badge={broken ? "invisible" : "visible"} tone={broken ? "broken" : "ok"}>
      <div className="absolute inset-0 bg-[#1D1D1F]" />
      <div className="absolute inset-0 flex items-center justify-center gap-3">
        <button className="px-3 py-2 rounded-lg bg-white/10 text-white text-xs">Cancel</button>
        <button
          className={`px-3 py-2 rounded-lg bg-[#0071E3] text-white text-xs ${broken
            ? "outline outline-1 outline-white/5"
            : variant === "glow" ? "shadow-[inset_0_0_0_2px_#fff,inset_0_0_0_4px_#0071E3]"
            : variant === "tint" ? "bg-[#0A84FF]"
            : "outline outline-2 outline-offset-2 outline-[#0071E3]"}`}
        >
          Confirm
        </button>
      </div>
    </Frame>
  );
}

function EmptyCrash({ variant }) {
  const broken = variant === "before";
  const seed = variant === "seed";
  const retry = variant === "retry";
  return (
    <Frame label="Empty state" badge={broken ? "crash" : "graceful"} tone={broken ? "broken" : "ok"}>
      {broken ? (
        <div className="absolute inset-3 rounded-md bg-white border border-[#FF3B30]/30 p-3">
          <div className="text-[10px] text-[#FF3B30] uppercase tracking-[0.18em]">Runtime error</div>
          <div className="font-mono text-[11px] text-[#FF3B30] mt-2 leading-relaxed">TypeError: Cannot read properties of null (reading &apos;length&apos;)</div>
        </div>
      ) : retry ? (
        <div className="absolute inset-0 flex items-center justify-center flex-col gap-2">
          <div className="text-xs text-[#86868B]">Something went wrong.</div>
          <button className="h-8 px-3 rounded-full bg-[#1D1D1F] text-white text-[11px]">Retry</button>
        </div>
      ) : seed ? (
        <div className="absolute inset-3 grid grid-cols-2 gap-2">
          <div className="rounded-lg border border-dashed border-black/15 p-2 text-[10px] text-[#86868B]">Example project</div>
          <div className="rounded-lg border border-black/10 p-2 text-[10px] text-[#1D1D1F]/70">+ Add yours</div>
        </div>
      ) : (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 px-6 text-center">
          <div className="w-10 h-10 rounded-2xl bg-[#F5F5F7]" />
          <div className="font-medium text-sm">No projects yet</div>
          <div className="text-[11px] text-[#86868B]">Start your first run and Atmos will fill this with insights.</div>
        </div>
      )}
    </Frame>
  );
}

function ImageLcp({ variant }) {
  const broken = variant === "before";
  const grad = variant === "gradient";
  const lqip = variant === "lqip";
  return (
    <Frame label="Hero performance" badge={broken ? "2.4 MB · 4.8s" : "120 KB · 1.1s"} tone={broken ? "broken" : "ok"}>
      <div className="absolute inset-3 rounded-md overflow-hidden">
        {broken ? (
          <div className="absolute inset-0 bg-[#1D1D1F]/10 flex items-center justify-center">
            <div className="text-[#86868B] text-[10px] uppercase tracking-[0.18em]">2400 KB · PNG</div>
          </div>
        ) : grad ? (
          <div className="absolute inset-0 bg-gradient-to-br from-[#0071E3] via-[#34C759] to-[#FF9500]" />
        ) : lqip ? (
          <div className="absolute inset-0 bg-gradient-to-br from-[#FFEBC4] to-[#86868B] blur-sm" />
        ) : (
          <div className="absolute inset-0 bg-gradient-to-br from-[#0A84FF] to-[#0040AF]" />
        )}
        <div className="absolute bottom-2 left-2 text-[10px] text-white font-medium">
          {broken ? "LCP 4.8s · blocking" : grad ? "0 KB CSS" : lqip ? "LQIP 12 B placeholder" : "AVIF · LCP 1.1s"}
        </div>
      </div>
    </Frame>
  );
}

function CurrencyPrecision({ variant }) {
  const broken = variant === "before";
  return (
    <Frame label="Checkout total" badge={broken ? "rounded" : "exact"} tone={broken ? "broken" : "ok"}>
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
        <div className="text-[10px] uppercase tracking-[0.18em] text-[#86868B]">Invoice</div>
        <div className="font-display text-3xl tabular-nums" style={{ color: broken ? "#FF3B30" : "#1D1D1F" }}>
          {broken ? "$10,000.00" : "$9,999.99"}
        </div>
        <div className="text-[10px] text-[#86868B]">
          {broken ? "drift +$0.01" : variant === "server" ? "server-authoritative" : variant === "decimal" ? "Decimal.js" : "exact decimal math"}
        </div>
      </div>
    </Frame>
  );
}

function DeepCheckout({ variant }) {
  const broken = variant === "before";
  const express = variant === "express";
  const two = variant === "two";
  const steps = broken ? ["Cart", "Address", "Shipping", "Billing", "Review", "Confirm", "Pay"] : two ? ["Email", "Pay"] : ["Cart", "Address", "Pay"];
  return (
    <Frame label="Checkout funnel" badge={broken ? "7 clicks" : `${steps.length} clicks`} tone={broken ? "broken" : "ok"}>
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 px-4">
        {express ? (
          <>
            <button className="h-9 w-44 rounded-lg bg-[#1D1D1F] text-white text-[11px]"> Pay</button>
            <button className="h-9 w-44 rounded-lg bg-white border border-black/15 text-[11px]">G Pay</button>
            <div className="text-[10px] text-[#86868B] mt-1">or single-page checkout below</div>
          </>
        ) : (
          <div className="flex items-center gap-1.5 flex-wrap justify-center">
            {steps.map((s, i) => (
              <span key={i} className={`text-[10px] rounded-full px-2 py-1 ${i === steps.length - 1 ? "bg-[#0071E3] text-white" : "bg-white border border-black/10 text-[#1D1D1F]/80"}`}>
                {s}
              </span>
            ))}
          </div>
        )}
      </div>
    </Frame>
  );
}

function CalendarClip({ variant }) {
  const broken = variant === "before";
  const clamp = variant === "clamp";
  const popout = variant === "popout";
  return (
    <Frame label="Calendar event" badge={broken ? "clipped" : "truncated"} tone={broken ? "broken" : "ok"}>
      <div className="absolute inset-3 grid grid-cols-4 gap-1">
        <div className="col-span-1 rounded bg-[#0071E3] text-[9px] text-white p-1 leading-tight">
          {broken ? "Quarterly business review with finance & ops" : clamp ? "Quarterly business review" : popout ? "QBR…" : "Quarterly business…"}
        </div>
        <div className="col-span-1 rounded bg-white border border-black/10 text-[9px] p-1">10:30 Sync</div>
        <div className="col-span-1 rounded bg-white border border-black/10 text-[9px] p-1">11:00 1:1</div>
        <div className="col-span-1 rounded bg-white border border-black/10 text-[9px] p-1">12:00 Lunch</div>
        {popout && (
          <div className="absolute top-3 left-3 w-40 rounded-md bg-white shadow-lg border border-black/5 p-2 text-[10px]">
            <div className="font-medium">Quarterly Business Review</div>
            <div className="text-[#86868B]">9:00 – 10:00 · 6 attendees</div>
          </div>
        )}
      </div>
    </Frame>
  );
}

function DstDoublebook({ variant }) {
  const broken = variant === "before";
  return (
    <Frame label="DST day" badge={broken ? "double-booked" : "single"} tone={broken ? "broken" : "ok"}>
      <div className="absolute inset-3 flex flex-col gap-1">
        <div className="text-[10px] uppercase tracking-[0.18em] text-[#86868B]">Mon · Mar 12</div>
        <div className={`rounded bg-[#0071E3] text-[10px] text-white p-1 ${broken ? "" : ""}`}>9:00 Team standup</div>
        {broken && <div className="rounded bg-[#FF3B30] text-[10px] text-white p-1">9:00 Team standup (dup)</div>}
        <div className="rounded bg-white border border-black/10 text-[10px] p-1">10:00 1:1</div>
        <div className="rounded bg-white border border-black/10 text-[10px] p-1">11:00 Design crit</div>
      </div>
    </Frame>
  );
}

function GridFreeze({ variant }) {
  const broken = variant === "before";
  return (
    <Frame label="Data grid" badge={broken ? "frozen 6s" : "interactive"} tone={broken ? "broken" : "ok"}>
      <div className="absolute inset-3 rounded-md bg-white border border-black/10 overflow-hidden">
        <div className="px-2 py-1 text-[10px] uppercase tracking-[0.18em] text-[#86868B] border-b border-black/5">10,000 rows</div>
        <div className="p-2 grid gap-0.5">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-2.5 rounded bg-[#F5F5F7]" style={{ opacity: broken ? 0.5 : 1 }} />
          ))}
        </div>
        {broken && (
          <div className="absolute inset-0 bg-white/40 flex items-center justify-center">
            <div className="text-[10px] text-[#FF3B30] uppercase tracking-[0.18em]">main thread blocked</div>
          </div>
        )}
      </div>
    </Frame>
  );
}

function CardOverload({ variant }) {
  const broken = variant === "before";
  const bento = variant === "bento";
  const tabs = variant === "tabs";
  return (
    <Frame label="Dashboard overview" badge={broken ? "24 cards" : "1 hero + 6"} tone={broken ? "broken" : "ok"}>
      {tabs && (
        <div className="absolute top-3 left-3 right-3 flex gap-1.5">
          {["For me", "Team", "Org"].map((t, i) => (
            <span key={i} className={`text-[10px] rounded-full px-2 py-0.5 ${i === 0 ? "bg-[#0071E3] text-white" : "bg-white border border-black/10"}`}>{t}</span>
          ))}
        </div>
      )}
      <div className={`absolute inset-3 ${tabs ? "top-9" : ""} grid gap-1 ${broken ? "grid-cols-6 grid-rows-4" : bento ? "grid-cols-3 grid-rows-3" : "grid-cols-3 grid-rows-3"}`}>
        {broken
          ? Array.from({ length: 24 }).map((_, i) => <div key={i} className="rounded bg-white border border-black/5" />)
          : bento
            ? (
              <>
                <div className="col-span-2 row-span-2 rounded-md bg-white border border-black/10 p-2 flex flex-col justify-between">
                  <div className="text-[9px] uppercase tracking-[0.18em] text-[#86868B]">Revenue</div>
                  <div className="font-display text-2xl tabular-nums">$1.2M</div>
                </div>
                {Array.from({ length: 5 }).map((_, i) => <div key={i} className="rounded bg-white border border-black/5" />)}
              </>
            )
            : (
              <>
                <div className="col-span-3 row-span-1 rounded-md bg-white border border-black/10 p-2 flex items-end justify-between">
                  <div className="text-[9px] uppercase tracking-[0.18em] text-[#86868B]">Revenue</div>
                  <div className="font-display text-2xl tabular-nums">$1.2M</div>
                </div>
                {Array.from({ length: 6 }).map((_, i) => <div key={i} className="rounded bg-white border border-black/5" />)}
              </>
            )}
      </div>
    </Frame>
  );
}

function ErrorJargon({ variant }) {
  const broken = variant === "before";
  const action = variant === "action";
  const chat = variant === "chat";
  return (
    <Frame label="Payment error" badge={broken ? "jargon" : "plain"} tone={broken ? "broken" : "ok"}>
      <div className="absolute inset-3 rounded-md bg-white border border-black/10 p-3 flex flex-col gap-2">
        <div className="text-[10px] uppercase tracking-[0.18em]" style={{ color: broken ? "#FF3B30" : "#34C759" }}>
          {broken ? "Error #405" : "Payment couldn't go through"}
        </div>
        {broken ? (
          <div className="text-xs text-[#1D1D1F]/70">A server error occurred. Try again later.</div>
        ) : (
          <div className="text-xs text-[#1D1D1F]/85">Your payment couldn&apos;t be processed.<br/>No funds were deducted. Please try again.</div>
        )}
        {action && (
          <div className="flex gap-2 mt-1">
            <button className="text-[10px] h-7 rounded-full bg-[#0071E3] text-white px-3">Try another card</button>
            <button className="text-[10px] h-7 rounded-full bg-white border border-black/15 px-3">Pay later</button>
          </div>
        )}
        {chat && (
          <div className="mt-1 text-[10px] text-[#0071E3]">Chat with support →</div>
        )}
      </div>
    </Frame>
  );
}

/* ---------- Router ---------------------------------------------------- */

const SCENE_REGISTRY = {
  "cta-overlap": CtaOverlap,
  "aria-form": AriaForm,
  "deep-nav": DeepNav,
  "focus-ring": FocusRing,
  "empty-crash": EmptyCrash,
  "image-lcp": ImageLcp,
  "currency-precision": CurrencyPrecision,
  "deep-checkout": DeepCheckout,
  "calendar-clip": CalendarClip,
  "dst-doublebook": DstDoublebook,
  "grid-freeze": GridFreeze,
  "card-overload": CardOverload,
  "error-jargon": ErrorJargon,
};

export default function Scene({ scene, variant = "after", animate = false }) {
  const Comp = SCENE_REGISTRY[scene] || CtaOverlap;
  return <Comp variant={variant} animate={animate} />;
}

/* ---------- Playback player (live recording) -------------------------- */

export function ScenePlayer({ scene, steps = [], currentStep = -1, status = "running" }) {
  // Cycle scene "highlight" variants per step to feel like a recording.
  const variants = useMemo(() => {
    // Always start at "before" to show the issue; flick to "after" on pass.
    return steps.map((_, i) => (i === steps.length - 1 && status === "pass" ? "after" : "before"));
  }, [steps, status]);

  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (status !== "running") return;
    const id = setInterval(() => setTick((t) => t + 1), 600);
    return () => clearInterval(id);
  }, [status]);

  const variant = variants[Math.max(0, currentStep)] || "before";
  return (
    <div className="relative" data-testid="scene-player">
      <Scene scene={scene} variant={variant} animate />
      <div className="absolute top-2 right-2 flex items-center gap-1.5 text-[10px] uppercase tracking-[0.18em] rounded-full bg-white/80 backdrop-blur px-2 py-1 border border-black/5">
        <span className={`w-1.5 h-1.5 rounded-full ${status === "running" ? "bg-[#FF3B30] live-dot" : status === "pass" ? "bg-[#34C759]" : status === "fail" ? "bg-[#FF3B30]" : "bg-[#FF9500]"}`} />
        rec · step {Math.min(currentStep + 1, steps.length)}/{steps.length}
        <span className="hidden">{tick}</span>
      </div>
    </div>
  );
}
