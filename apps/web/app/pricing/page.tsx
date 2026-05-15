import Link from "next/link";
import {
  ArrowRight,
  Check,
  Mail,
  Minus,
  Phone,
  Sparkles,
  X,
} from "lucide-react";


/**
 * Public pricing page at /pricing — server-rendered, no auth check.
 *
 * Layout:
 *   1. Sticky nav (same as landing).
 *   2. Header — headline + sub.
 *   3. Three-card pricing grid (Khởi đầu / Chuyên nghiệp / Doanh nghiệp).
 *   4. Comparison table — exhaustive feature matrix.
 *   5. FAQ.
 *   6. Demo request CTA.
 */
export const metadata = {
  title: "Gói cước — AEC Platform",
  description:
    "3 gói cước minh bạch cho mọi quy mô nhà thầu. Khởi đầu miễn phí, Chuyên nghiệp 4.9M VNĐ/tháng, Doanh nghiệp tuỳ chỉnh.",
};


export default function PricingPage() {
  return (
    <div className="min-h-screen bg-white">
      <NavBar />
      <Header />
      <PlanCards />
      <ComparisonTable />
      <Faq />
      <DemoCta />
      <Footer />
    </div>
  );
}


function NavBar() {
  return (
    <nav className="sticky top-0 z-40 border-b border-slate-200 bg-white/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
        <Link href="/" className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-slate-900 text-sm font-bold text-white">
            AEC
          </div>
          <span className="font-semibold text-slate-900">AEC Platform</span>
        </Link>
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="hidden text-sm text-slate-700 hover:text-slate-900 sm:inline"
          >
            Trang chủ
          </Link>
          <a
            href="mailto:sales@aec-platform.vn"
            className="hidden text-sm text-slate-700 hover:text-slate-900 sm:inline"
          >
            Liên hệ sales
          </a>
          <Link
            href="/login"
            className="rounded-md px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-100"
          >
            Đăng nhập
          </Link>
          <Link
            href="/signup"
            className="rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-slate-800"
          >
            Dùng thử miễn phí
          </Link>
        </div>
      </div>
    </nav>
  );
}


function Header() {
  return (
    <section className="mx-auto max-w-4xl px-4 py-16 text-center">
      <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700 ring-1 ring-blue-200">
        <Sparkles size={11} />
        Tất cả 14 module được kích hoạt trên mọi gói
      </span>
      <h1 className="mt-5 text-4xl font-bold text-slate-900 sm:text-5xl">
        Giá đơn giản, không phụ phí
      </h1>
      <p className="mx-auto mt-4 max-w-2xl text-slate-600">
        Chỉ trả tiền cho quy mô bạn cần. Khác biệt giữa các gói là giới hạn
        dự án / lưu trữ / quota AI — không phải tính năng. Mọi module luôn
        có sẵn để bạn thử.
      </p>
    </section>
  );
}


function PlanCards() {
  const plans = [
    {
      slug: "starter",
      name: "Khởi đầu",
      price: "Miễn phí",
      sub: "Cho nhóm 1-3 người đánh giá",
      highlight: false,
      cta: "Đăng ký miễn phí",
      ctaHref: "/signup",
      features: [
        "1 dự án",
        "3 thành viên",
        "2 GB lưu trữ bản vẽ",
        "200 lượt CodeGuard / tháng",
        "Tất cả 14 module",
      ],
    },
    {
      slug: "pro",
      name: "Chuyên nghiệp",
      price: "4.900.000 ₫",
      sub: "/ tháng (chưa VAT)",
      highlight: true,
      cta: "Bắt đầu thử 30 ngày",
      ctaHref: "/signup?plan=pro",
      features: [
        "10 dự án",
        "25 thành viên",
        "50 GB lưu trữ bản vẽ",
        "1.000 lượt CodeGuard / tháng",
        "PDF báo cáo dự án + biên bản bàn giao",
        "Xuất KTNN audit log (CSV + XLSX có SHA-256)",
        "Email hỗ trợ trong ngày",
      ],
    },
    {
      slug: "enterprise",
      name: "Doanh nghiệp",
      price: "Liên hệ",
      sub: "Cho SOE + tổng thầu lớn",
      highlight: false,
      cta: "Yêu cầu báo giá",
      ctaHref: "mailto:sales@aec-platform.vn?subject=Quan%20t%C3%A2m%20g%C3%B3i%20Doanh%20nghi%E1%BB%87p",
      features: [
        "Không giới hạn dự án + người dùng",
        "Lưu trữ tuỳ chọn (MinIO on-prem hoặc cloud)",
        "SSO Microsoft Entra + Google Workspace",
        "SLA 99.9% — cam kết uptime trong hợp đồng",
        "Custom QCVN ingest",
        "Hỗ trợ qua hotline + Slack",
      ],
    },
  ];

  return (
    <section className="mx-auto max-w-6xl px-4 pb-16">
      <div className="grid gap-6 md:grid-cols-3">
        {plans.map((p) => (
          <div
            key={p.slug}
            className={`relative flex flex-col rounded-2xl p-6 ${
              p.highlight
                ? "bg-slate-900 text-white shadow-2xl ring-2 ring-blue-500"
                : "border border-slate-200 bg-white text-slate-900"
            }`}
          >
            {p.highlight && (
              <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-blue-500 px-3 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white">
                Phổ biến
              </span>
            )}
            <h3 className="text-lg font-bold">{p.name}</h3>
            <div className="mt-3">
              <p className="text-3xl font-bold">{p.price}</p>
              <p className={`text-xs ${p.highlight ? "text-slate-400" : "text-slate-500"}`}>
                {p.sub}
              </p>
            </div>
            <ul className={`mt-6 flex-1 space-y-2 text-sm ${p.highlight ? "text-slate-200" : "text-slate-700"}`}>
              {p.features.map((f) => (
                <li key={f} className="flex items-start gap-2">
                  <Check
                    size={14}
                    className={`mt-0.5 flex-shrink-0 ${
                      p.highlight ? "text-emerald-400" : "text-emerald-500"
                    }`}
                  />
                  {f}
                </li>
              ))}
            </ul>
            <a
              href={p.ctaHref}
              className={`mt-6 inline-flex items-center justify-center gap-1 rounded-md px-4 py-2.5 text-sm font-medium ${
                p.highlight
                  ? "bg-white text-slate-900 hover:bg-slate-100"
                  : p.slug === "enterprise"
                  ? "bg-slate-900 text-white hover:bg-slate-800"
                  : "bg-blue-600 text-white hover:bg-blue-700"
              }`}
            >
              {p.cta}
              <ArrowRight size={13} />
            </a>
          </div>
        ))}
      </div>
    </section>
  );
}


function ComparisonTable() {
  const rows: Array<{
    label: string;
    starter: string | boolean;
    pro: string | boolean;
    enterprise: string | boolean;
    section?: string;
  }> = [
    { section: "Giới hạn", label: "Dự án tối đa", starter: "1", pro: "10", enterprise: "Không giới hạn" },
    { label: "Thành viên", starter: "3", pro: "25", enterprise: "Không giới hạn" },
    { label: "Lưu trữ bản vẽ", starter: "2 GB", pro: "50 GB", enterprise: "Tuỳ chỉnh" },
    { label: "Quota CodeGuard / tháng", starter: "200", pro: "1.000", enterprise: "5.000+" },
    { section: "Module thi công", label: "Pulse — điều phối", starter: true, pro: true, enterprise: true },
    { label: "Tiến độ dự án (SchedulePilot)", starter: true, pro: true, enterprise: true },
    { label: "SiteEye — giám sát AI", starter: true, pro: true, enterprise: true },
    { label: "Nhật ký công trình", starter: true, pro: true, enterprise: true },
    { label: "Lệnh thay đổi", starter: true, pro: true, enterprise: true },
    { section: "Module thiết kế + đấu thầu", label: "CodeGuard — đối chiếu QCVN", starter: true, pro: true, enterprise: true },
    { label: "Drawbridge — Q&A bản vẽ", starter: true, pro: true, enterprise: true },
    { label: "BidRadar — săn gói thầu", starter: true, pro: true, enterprise: true },
    { label: "WinWork — đề xuất + báo giá", starter: true, pro: true, enterprise: true },
    { label: "CostPulse — dự toán + RFQ", starter: true, pro: true, enterprise: true },
    { section: "Module bàn giao", label: "Handover + biên bản PDF", starter: false, pro: true, enterprise: true },
    { label: "Punch list", starter: true, pro: true, enterprise: true },
    { section: "Báo cáo & Xuất dữ liệu", label: "PDF báo cáo dự án 1 trang", starter: false, pro: true, enterprise: true },
    { label: "PDF biên bản bàn giao công trình", starter: false, pro: true, enterprise: true },
    { label: "Xuất KTNN audit log (CSV + XLSX SHA-256)", starter: false, pro: true, enterprise: true },
    { label: "Xuất Excel toàn bộ entity (dự án, NCC, RFI…)", starter: true, pro: true, enterprise: true },
    { section: "Bảo mật & Đăng nhập", label: "Email + mật khẩu", starter: true, pro: true, enterprise: true },
    { label: "SSO Google Workspace", starter: false, pro: false, enterprise: true },
    { label: "SSO Microsoft Entra (Azure AD)", starter: false, pro: false, enterprise: true },
    { label: "Audit log mọi thay đổi (append-only)", starter: true, pro: true, enterprise: true },
    { label: "Tenant isolation qua Postgres RLS", starter: true, pro: true, enterprise: true },
    { section: "Hạ tầng", label: "Cloud (Supabase Singapore)", starter: true, pro: true, enterprise: true },
    { label: "MinIO on-prem cho bản vẽ", starter: false, pro: false, enterprise: true },
    { label: "Multi-region active-passive failover", starter: false, pro: false, enterprise: true },
    { label: "SLA 99.9% có cam kết hợp đồng", starter: false, pro: false, enterprise: true },
    { section: "Hỗ trợ", label: "Tài liệu hướng dẫn + email cộng đồng", starter: true, pro: true, enterprise: true },
    { label: "Email hỗ trợ trong ngày làm việc", starter: false, pro: true, enterprise: true },
    { label: "Hotline + Slack chung dùng", starter: false, pro: false, enterprise: true },
    { label: "Đào tạo on-site cho team mới", starter: false, pro: false, enterprise: true },
  ];

  return (
    <section className="mx-auto max-w-6xl px-4 py-16">
      <h2 className="text-3xl font-bold text-slate-900">So sánh chi tiết</h2>
      <p className="mt-2 text-slate-600">
        Mọi tính năng, mọi gói, không có gạch chân nhỏ.
      </p>
      <div className="mt-8 overflow-x-auto rounded-xl border border-slate-200">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr>
              <th className="px-4 py-3 text-left font-medium text-slate-700">Tính năng</th>
              <th className="px-4 py-3 text-center font-medium text-slate-700">Khởi đầu</th>
              <th className="px-4 py-3 text-center font-medium text-blue-700">Chuyên nghiệp</th>
              <th className="px-4 py-3 text-center font-medium text-slate-700">Doanh nghiệp</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, idx) => (
              <tr
                key={r.label + idx}
                className={
                  r.section
                    ? "border-t border-slate-200 bg-slate-50/50"
                    : "border-t border-slate-100"
                }
              >
                <td className="px-4 py-2.5 text-slate-900">
                  {r.section && (
                    <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                      {r.section}
                    </p>
                  )}
                  {r.label}
                </td>
                <td className="px-4 py-2.5 text-center">
                  <CellValue value={r.starter} />
                </td>
                <td className="px-4 py-2.5 text-center">
                  <CellValue value={r.pro} highlight />
                </td>
                <td className="px-4 py-2.5 text-center">
                  <CellValue value={r.enterprise} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}


function CellValue({ value, highlight }: { value: string | boolean; highlight?: boolean }) {
  if (value === true) {
    return <Check size={16} className={highlight ? "mx-auto text-blue-600" : "mx-auto text-emerald-500"} />;
  }
  if (value === false) {
    return <Minus size={14} className="mx-auto text-slate-300" />;
  }
  return <span className={highlight ? "font-semibold text-blue-700" : "text-slate-700"}>{value}</span>;
}


function Faq() {
  const items = [
    {
      q: "Tôi có thể đổi gói bất cứ lúc nào không?",
      a: "Có. Khi nâng gói, hiệu lực ngay lập tức + tính prorated cho phần còn lại của tháng. Khi hạ gói, hiệu lực từ kỳ thanh toán tiếp theo.",
    },
    {
      q: "Thanh toán bằng cách nào?",
      a: "Hai cách: (1) VietQR chuyển khoản qua app ngân hàng VN — hoá đơn điện tử tự động phát hành; (2) Thẻ tín dụng quốc tế qua Stripe. Thẻ Napas nội địa hiện chưa hỗ trợ.",
    },
    {
      q: "Quota CodeGuard hết thì sao?",
      a: "Endpoint /scan và /query trả 429 cho đến đầu tháng tiếp theo hoặc khi nâng gói. Module CodeGuard vẫn xem được lịch sử + danh mục QCVN.",
    },
    {
      q: "Bản vẽ tôi upload có an toàn không?",
      a: "Có. Lưu trên Supabase Singapore (PROD) hoặc MinIO on-prem (Enterprise). Mã hoá at-rest + in-transit. Multi-tenant qua Postgres RLS — không có cross-tenant data leak. Audit log mọi truy cập.",
    },
    {
      q: "Có dùng được khi không có mạng không?",
      a: "PWA hoạt động offline ở mức cơ bản (xem trang đã cache, fallback offline screen). Tải ảnh công trường offline → tự sync khi mạng có lại. Mọi thao tác cần backend (scan, Q&A, lưu task) cần online.",
    },
    {
      q: "Có cần cài đặt gì trên máy không?",
      a: "Không. Đây là web app — chỉ cần Chrome/Safari/Edge. PWA có thể cài về home screen điện thoại. Capacitor native iOS/Android sẽ có trên App Store + Play Store cuối 2026.",
    },
    {
      q: "Đào tạo team mất bao lâu?",
      a: "Quản lý dự án: 1 giờ self-onboarding qua wizard. Engineer công trường: 30 phút (chỉ dùng SiteEye + Pulse). Quản lý cấp cao: 15 phút (dashboard tổng quan).",
    },
    {
      q: "Có thể tích hợp với phần mềm khác không?",
      a: "Có. REST API + Webhooks. SDK Python + TypeScript. Đã có connector sẵn cho MS Project (import lịch), Excel (BoQ, supplier directory), VnInvoice (e-invoice). Custom integration trong gói Doanh nghiệp.",
    },
  ];
  return (
    <section className="mx-auto max-w-4xl px-4 py-16">
      <h2 className="text-3xl font-bold text-slate-900">Câu hỏi thường gặp</h2>
      <dl className="mt-8 space-y-3">
        {items.map((f) => (
          <details
            key={f.q}
            className="group rounded-lg border border-slate-200 bg-white open:bg-slate-50"
          >
            <summary className="flex cursor-pointer items-center justify-between px-4 py-3 text-sm font-medium text-slate-900">
              {f.q}
              <span className="ml-4 text-slate-400 group-open:rotate-45">+</span>
            </summary>
            <p className="px-4 pb-4 text-sm text-slate-600">{f.a}</p>
          </details>
        ))}
      </dl>
    </section>
  );
}


function DemoCta() {
  return (
    <section className="mx-auto my-16 max-w-4xl rounded-2xl bg-gradient-to-br from-slate-900 to-blue-900 px-8 py-12 text-center text-white">
      <h2 className="text-3xl font-bold">Cần demo trước khi quyết định?</h2>
      <p className="mx-auto mt-3 max-w-2xl text-slate-300">
        Sales sẽ demo 30 phút trực tuyến với dữ liệu mẫu của ngành công nghiệp
        bạn (residential, office, industrial, infra). Trả lời mọi câu hỏi
        về tích hợp, on-prem, cấp phép VN.
      </p>
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <a
          href="mailto:sales@aec-platform.vn?subject=Đặt%20l%E1%BB%8Bch%20demo&body=T%C3%AAn%20c%C3%B4ng%20ty%3A%0AS%E1%BB%91%20l%C6%B0%E1%BB%A3ng%20d%E1%BB%B1%20%C3%A1n%2Fn%C4%83m%3A%0AT%C3%ADnh%20n%C4%83ng%20quan%20t%C3%A2m%20nh%E1%BA%A5t%3A"
          className="inline-flex items-center gap-1.5 rounded-md bg-white px-6 py-3 text-sm font-medium text-slate-900 hover:bg-slate-100"
        >
          <Mail size={14} />
          Đặt lịch demo qua email
        </a>
        <a
          href="tel:+842432000000"
          className="inline-flex items-center gap-1.5 rounded-md border border-white/30 bg-white/10 px-6 py-3 text-sm font-medium text-white hover:bg-white/20"
        >
          <Phone size={14} />
          Hotline: (024) 3200 0000
        </a>
      </div>
    </section>
  );
}


function Footer() {
  return (
    <footer className="border-t border-slate-200 bg-slate-50 py-10 text-sm text-slate-600">
      <div className="mx-auto max-w-6xl px-4 text-center text-xs text-slate-500">
        © {new Date().getFullYear()} AEC Platform. Mọi quyền được bảo lưu.
      </div>
    </footer>
  );
}
