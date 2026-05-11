import Link from "next/link";
import type { Route } from "next";

import { PageHeader } from "@aec/ui/primitives";

export const dynamic = "force-dynamic";

const SECTIONS: Array<{ href: Route; title: string; desc: string }> = [
  { href: "/costpulse/estimates", title: "Estimates", desc: "Browse, edit and approve cost estimates." },
  { href: "/costpulse/estimates/new", title: "New estimate", desc: "AI estimate from brief or drawings." },
  { href: "/costpulse/prices", title: "Price database", desc: "Live material prices + trend charts." },
  { href: "/costpulse/suppliers", title: "Suppliers", desc: "Directory of verified suppliers." },
  { href: "/costpulse/rfq", title: "RFQ manager", desc: "Send and track RFQs." },
];

export default function CostPulseHome(): JSX.Element {
  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <PageHeader
        title="CostPulse"
        description="Estimation & procurement intelligence."
      />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {SECTIONS.map((s) => (
          <Link
            key={s.href}
            href={s.href}
            className="rounded-lg border bg-card p-5 transition hover:border-primary/40 hover:shadow-sm"
          >
            <div className="text-lg font-semibold text-foreground">{s.title}</div>
            <div className="mt-1 text-sm text-muted-foreground">{s.desc}</div>
          </Link>
        ))}
      </div>
    </div>
  );
}
