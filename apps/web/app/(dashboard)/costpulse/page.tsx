import Link from "next/link";

export const dynamic = "force-dynamic";

const SECTIONS = [
  { href: "/costpulse/estimates", title: "Estimates", desc: "Browse, edit and approve cost estimates." },
  { href: "/costpulse/estimates/new", title: "New estimate", desc: "AI estimate from brief or drawings." },
  { href: "/costpulse/prices", title: "Price database", desc: "Live material prices + trend charts." },
  { href: "/costpulse/suppliers", title: "Suppliers", desc: "Directory of verified suppliers." },
  { href: "/costpulse/rfq", title: "RFQ manager", desc: "Send and track RFQs." },
];

export default function CostPulseHome(): JSX.Element {
  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <header>
        <h1 className="text-3xl font-bold text-slate-900">CostPulse</h1>
        <p className="text-slate-600">Estimation & procurement intelligence.</p>
      </header>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {SECTIONS.map((s) => (
          <Link
            key={s.href}
            href={s.href}
            className="rounded-lg border border-slate-200 bg-white p-5 transition hover:border-slate-300 hover:shadow-sm"
          >
            <div className="text-lg font-semibold text-slate-900">{s.title}</div>
            <div className="mt-1 text-sm text-slate-600">{s.desc}</div>
          </Link>
        ))}
      </div>
    </div>
  );
}
