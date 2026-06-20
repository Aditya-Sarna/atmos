export default function AtmosMark({ size = 28, pulse = false, className = "" }) {
  return (
    <span
      className={`inline-flex items-center gap-2 ${className}`}
      data-testid="atmos-mark"
      aria-label="Atmos"
    >
      <svg
        width={size}
        height={size}
        viewBox="0 0 32 32"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className={pulse ? "live-dot" : ""}
      >
        <defs>
          <radialGradient id="atmosCore" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#1D1D1F" stopOpacity="1" />
            <stop offset="100%" stopColor="#1D1D1F" stopOpacity="0.85" />
          </radialGradient>
        </defs>
        <circle cx="16" cy="16" r="6" fill="url(#atmosCore)" />
        <circle cx="16" cy="16" r="11" stroke="#1D1D1F" strokeWidth="1.25" strokeOpacity="0.35" />
        <circle cx="16" cy="16" r="15" stroke="#1D1D1F" strokeWidth="1" strokeOpacity="0.18" />
        <circle cx="28" cy="11" r="1.6" fill="#0071E3" />
      </svg>
      <span className="font-display font-medium tracking-tight" style={{ fontSize: size * 0.62 }}>
        atmos
      </span>
    </span>
  );
}
