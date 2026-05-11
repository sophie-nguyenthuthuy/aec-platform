import Link from "next/link";
import type { Route } from "next";

import { PageHeader } from "@aec/ui/primitives";

export const dynamic = "force-dynamic";

const SECTIONS: Array<{ href: Route; title: string; desc: string }> = [
  { href: "/costpulse/estimates", title: "Dự toán", desc: "Xem, chỉnh sửa và duyệt dự toán chi phí." },
  { href: "/costpulse/estimates/new", title: "Dự toán mới", desc: "Lập dự toán bằng AI từ brief hoặc bản vẽ." },
  { href: "/costpulse/prices", title: "Cơ sở dữ liệu giá", desc: "Giá vật liệu thực tế và biểu đồ xu hướng." },
  { href: "/costpulse/suppliers", title: "Nhà cung cấp", desc: "Danh mục nhà cung cấp đã xác minh." },
  { href: "/costpulse/rfq", title: "Quản lý RFQ", desc: "Gửi và theo dõi yêu cầu báo giá." },
];

export default function CostPulseHome(): JSX.Element {
  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <PageHeader
        title="CostPulse"
        description="Lập dự toán & thu mua thông minh."
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
