const NAMES = [
  "Apple", "Stripe", "Linear", "Notion", "Figma", "Google", "Shopify",
  "Amazon", "PayPal", "Vercel", "Fantastical", "Wise", "Microsoft",
];

export default function BenchmarkMarquee() {
  const doubled = [...NAMES, ...NAMES];
  return (
    <div className="overflow-hidden border-y border-black/5 bg-white" data-testid="benchmark-marquee">
      <div className="flex marquee-track gap-12 py-6 whitespace-nowrap">
        {doubled.map((n, i) => (
          <span
            key={i}
            className="font-display text-2xl md:text-3xl text-[#1D1D1F]/35 tracking-tight font-medium"
          >
            {n}
          </span>
        ))}
      </div>
    </div>
  );
}
