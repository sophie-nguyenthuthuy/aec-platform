"use client";

import Link from "next/link";
import {
  ArrowRight,
  Building2,
  CheckCircle2,
  Layers,
  Lock,
  Mail,
  Phone,
  Shield,
  Sparkles,
  Zap,
} from "lucide-react";


/**
 * Public marketing landing page rendered at `/` for unauthenticated
 * visitors. Logged-in users redirect to /inbox before reaching this
 * component (see `app/page.tsx`).
 *
 * Layout (top → bottom):
 *   1. Sticky nav with logo + CTAs.
 *   2. Hero — Vietnamese-first headline, 1-line value, primary +
 *      secondary CTAs.
 *   3. Trust strip — "Tin dùng bởi N nhà thầu nhà nước + tư nhân"
 *      with sample logos placeholder.
 *   4. Module grid — 14 cards, one per module, with VN tagline.
 *   5. Lifecycle bar — phases from pháp lý → bàn giao with the
 *      matching modules.
 *   6. Why AEC strip — 3 differentiators (VN-first, AI-built-in,
 *      data sovereignty).
 *   7. Pricing teaser linking to /pricing.
 *   8. CTA footer with form-redirect to /signup.
 *
 * Everything is static; no API calls. Built for fast cold-start +
 * good SEO (server-rendered React).
 */


export default function LandingPage() {
  return (
    <div className="min-h-screen bg-white">
      <NavBar />
      <Hero />
      <TrustStrip />
      <ModulesGrid />
      <LifecycleBar />
      <Differentiators />
      <PricingTeaser />
      <FinalCta />
      <Footer />
    </div>
  );
}


// ---------- Sections ----------


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
            href="/pricing"
            className="hidden text-sm text-slate-700 hover:text-slate-900 sm:inline"
          >
            Gói cước
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


function Hero() {
  return (
    <section className="relative overflow-hidden">
      <div className="absolute inset-0 -z-10 bg-gradient-to-br from-slate-50 via-white to-blue-50" />
      <div className="mx-auto max-w-6xl px-4 py-20 sm:py-24">
        <div className="max-w-3xl">
          <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700 ring-1 ring-blue-200">
            <Sparkles size={11} />
            Nền tảng AI dành riêng cho ngành xây dựng Việt Nam
          </span>
          <h1 className="mt-5 text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl sm:leading-tight">
            Quản lý toàn bộ vòng đời{" "}
            <span className="bg-gradient-to-r from-blue-600 to-cyan-600 bg-clip-text text-transparent">
              dự án xây dựng
            </span>{" "}
            trong một nền tảng.
          </h1>
          <p className="mt-5 max-w-2xl text-lg text-slate-600">
            Từ săn gói thầu, làm hồ sơ thiết kế đối chiếu QCVN, đến giám sát
            công trường bằng AI và bàn giao công trình — AEC Platform tích hợp
            14 module được thiết kế riêng cho nhà thầu Việt.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link
              href="/signup"
              className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-5 py-3 text-sm font-medium text-white hover:bg-blue-700"
            >
              Dùng thử miễn phí 30 ngày
              <ArrowRight size={14} />
            </Link>
            <a
              href="mailto:sales@aec-platform.vn?subject=Đặt%20l%E1%BB%8Bch%20demo"
              className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-5 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Đặt lịch demo
            </a>
          </div>
          <p className="mt-3 text-xs text-slate-500">
            Không cần thẻ tín dụng · Cài đặt 5 phút · Hỗ trợ tiếng Việt
          </p>
        </div>
      </div>
    </section>
  );
}


function TrustStrip() {
  return (
    <section className="border-y border-slate-100 bg-white py-10">
      <div className="mx-auto max-w-6xl px-4">
        <p className="text-center text-xs uppercase tracking-wider text-slate-500">
          Được tin dùng bởi các nhà thầu hàng đầu Việt Nam
        </p>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-x-12 gap-y-4 opacity-60">
          {/* Placeholder logo strip — replace with actual partner logos */}
          {["VINACONEX", "COTECCONS", "HÒA BÌNH", "DELTA", "HUDLAND"].map((co) => (
            <span
              key={co}
              className="font-bold tracking-widest text-slate-400"
            >
              {co}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}


function ModulesGrid() {
  const modules: Array<{ name: string; vn_tag: string; group: string }> = [
    { name: "WinWork", vn_tag: "Đề xuất & Báo giá", group: "Đấu thầu" },
    { name: "BidRadar", vn_tag: "Săn gói thầu nhà nước", group: "Đấu thầu" },
    { name: "CostPulse", vn_tag: "Dự toán & RFQ vật tư", group: "Đấu thầu" },
    { name: "CodeGuard", vn_tag: "Đối chiếu QCVN/TCVN", group: "Thiết kế" },
    { name: "Drawbridge", vn_tag: "Q&A bản vẽ", group: "Thiết kế" },
    { name: "PermitFlow", vn_tag: "Giấy phép xây dựng", group: "Pháp lý" },
    { name: "PCCC", vn_tag: "Phòng cháy chữa cháy", group: "Pháp lý" },
    { name: "Tiến độ dự án", vn_tag: "Gantt + đường găng + AI rủi ro", group: "Thi công" },
    { name: "Pulse", vn_tag: "Điều phối dự án", group: "Thi công" },
    { name: "SiteEye", vn_tag: "Giám sát công trường AI", group: "Thi công" },
    { name: "Nhật ký", vn_tag: "Báo cáo nhật trình", group: "Thi công" },
    { name: "Lệnh thay đổi", vn_tag: "Change order tracking", group: "Thi công" },
    { name: "Handover", vn_tag: "Bàn giao + sổ tay vận hành", group: "Bàn giao" },
    { name: "Punch list", vn_tag: "Tồn đọng bàn giao", group: "Bàn giao" },
  ];

  return (
    <section id="modules" className="mx-auto max-w-6xl px-4 py-20">
      <div className="mx-auto max-w-2xl text-center">
        <h2 className="text-3xl font-bold text-slate-900">
          14 module phủ trọn vòng đời dự án
        </h2>
        <p className="mt-3 text-slate-600">
          Một tài khoản — toàn bộ module sẵn sàng. Không phải mua từng tính
          năng. Không phải tích hợp 5 phần mềm khác nhau.
        </p>
      </div>
      <div className="mt-12 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {modules.map((m) => (
          <div
            key={m.name}
            className="rounded-xl border border-slate-200 bg-white p-4 transition-shadow hover:shadow-md"
          >
            <p className="text-[10px] font-semibold uppercase tracking-wide text-blue-600">
              {m.group}
            </p>
            <p className="mt-1.5 font-semibold text-slate-900">{m.name}</p>
            <p className="mt-0.5 text-xs text-slate-600">{m.vn_tag}</p>
          </div>
        ))}
      </div>
    </section>
  );
}


function LifecycleBar() {
  const phases = [
    { name: "Pháp lý", color: "bg-amber-500", modules: "PermitFlow, PCCC" },
    { name: "Thiết kế", color: "bg-violet-500", modules: "CodeGuard, Drawbridge" },
    { name: "Đấu thầu", color: "bg-sky-500", modules: "BidRadar, WinWork, CostPulse" },
    { name: "Thi công", color: "bg-emerald-500", modules: "Pulse, SiteEye, Tiến độ, Nhật ký" },
    { name: "Bàn giao", color: "bg-rose-500", modules: "Handover, Punch list" },
  ];
  return (
    <section className="bg-slate-50 py-20">
      <div className="mx-auto max-w-6xl px-4">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-bold text-slate-900">
            Theo đúng quy trình thi công Việt Nam
          </h2>
          <p className="mt-3 text-slate-600">
            Sidebar nhóm module theo vòng đời dự án — nhân viên mới
            không phải học lại UI; mọi thứ đúng vị trí.
          </p>
        </div>
        <div className="mt-12 flex flex-col gap-2 sm:flex-row sm:gap-0">
          {phases.map((p, i) => (
            <div
              key={p.name}
              className="relative flex-1 rounded-md px-4 py-3 text-white sm:rounded-none sm:first:rounded-l-md sm:last:rounded-r-md"
              style={{
                background:
                  i === 0
                    ? "#f59e0b"
                    : i === 1
                    ? "#8b5cf6"
                    : i === 2
                    ? "#0ea5e9"
                    : i === 3
                    ? "#10b981"
                    : "#f43f5e",
              }}
            >
              <p className="text-sm font-bold">{p.name}</p>
              <p className="mt-0.5 text-xs opacity-90">{p.modules}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}


function Differentiators() {
  const items = [
    {
      icon: <Sparkles size={20} />,
      title: "AI tích hợp sâu — không phải gắn ngoài",
      body:
        "CodeGuard biết QCVN. Drawbridge đọc bản vẽ Việt. WinWork hiểu mẫu đề xuất nhà nước. AI làm việc với dữ liệu của bạn, không phải chuyển sang OpenAI Workbench rồi copy về.",
    },
    {
      icon: <Lock size={20} />,
      title: "Data sovereignty — dữ liệu ở Việt Nam",
      body:
        "Database + bản vẽ + báo cáo lưu tại Supabase Singapore (PROD) hoặc on-prem MinIO (Enterprise). Không gửi sang Mỹ. Phù hợp yêu cầu khách hàng nhà nước.",
    },
    {
      icon: <Building2 size={20} />,
      title: "Việt Nam-first, không phải bản dịch",
      body:
        "QCVN/TCVN ingest sẵn. VietQR thanh toán. Biên bản bàn giao đúng mẫu BXD. Không phải Procore dịch tiếng Việt — đây là phần mềm xây dựng VN.",
    },
  ];
  return (
    <section className="mx-auto max-w-6xl px-4 py-20">
      <div className="grid gap-6 sm:grid-cols-3">
        {items.map((it) => (
          <div key={it.title} className="rounded-xl border border-slate-200 bg-white p-6">
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-blue-100 text-blue-700">
              {it.icon}
            </div>
            <h3 className="mt-4 text-lg font-semibold text-slate-900">{it.title}</h3>
            <p className="mt-2 text-sm text-slate-600">{it.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}


function PricingTeaser() {
  return (
    <section className="bg-slate-900 py-20 text-white">
      <div className="mx-auto max-w-4xl px-4 text-center">
        <h2 className="text-3xl font-bold">Giá đơn giản, không bẫy hidden cost</h2>
        <p className="mt-3 text-slate-300">
          3 gói. Tất cả module luôn được kích hoạt. Gói khác nhau ở giới hạn
          dự án, lưu trữ, và quota AI.
        </p>
        <div className="mt-10 grid gap-4 sm:grid-cols-3">
          <PricingTile
            name="Khởi đầu"
            price="Miễn phí"
            highlight={false}
            features={["1 dự án", "3 thành viên", "Tất cả 14 module"]}
          />
          <PricingTile
            name="Chuyên nghiệp"
            price="4.9 triệu VNĐ"
            sub="/ tháng (chưa VAT)"
            highlight
            features={["10 dự án", "25 thành viên", "PDF báo cáo + xuất KTNN"]}
          />
          <PricingTile
            name="Doanh nghiệp"
            price="Liên hệ"
            highlight={false}
            features={["Không giới hạn", "SSO + on-prem", "SLA 99.9%"]}
          />
        </div>
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          <Link
            href="/pricing"
            className="inline-flex items-center gap-1.5 rounded-md bg-white px-5 py-3 text-sm font-medium text-slate-900 hover:bg-slate-100"
          >
            Xem so sánh đầy đủ
            <ArrowRight size={14} />
          </Link>
        </div>
      </div>
    </section>
  );
}


function PricingTile({
  name,
  price,
  sub,
  features,
  highlight,
}: {
  name: string;
  price: string;
  sub?: string;
  features: string[];
  highlight: boolean;
}) {
  return (
    <div
      className={`rounded-xl p-5 text-left ${
        highlight ? "bg-blue-600 ring-4 ring-blue-300/30" : "bg-slate-800"
      }`}
    >
      <p className={`text-sm ${highlight ? "text-blue-100" : "text-slate-400"}`}>
        {name}
      </p>
      <p className="mt-1 text-2xl font-bold">{price}</p>
      {sub && (
        <p className={`text-xs ${highlight ? "text-blue-200" : "text-slate-400"}`}>
          {sub}
        </p>
      )}
      <ul className={`mt-4 space-y-1 text-xs ${highlight ? "text-blue-50" : "text-slate-300"}`}>
        {features.map((f) => (
          <li key={f} className="flex items-start gap-1.5">
            <CheckCircle2 size={12} className="mt-0.5 flex-shrink-0" />
            <span>{f}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}


function FinalCta() {
  return (
    <section className="mx-auto max-w-4xl px-4 py-20 text-center">
      <h2 className="text-3xl font-bold text-slate-900">
        Bắt đầu trong 5 phút
      </h2>
      <p className="mt-3 text-slate-600">
        Dùng thử miễn phí 30 ngày trên gói Chuyên nghiệp. Không cần thẻ tín
        dụng. Huỷ bất cứ lúc nào.
      </p>
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <Link
          href="/signup"
          className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-6 py-3 text-sm font-medium text-white hover:bg-blue-700"
        >
          Tạo tài khoản
          <ArrowRight size={14} />
        </Link>
        <a
          href="mailto:sales@aec-platform.vn?subject=Đặt%20l%E1%BB%8Bch%20demo"
          className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-6 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          Đặt lịch demo với sales
        </a>
      </div>
    </section>
  );
}


function Footer() {
  return (
    <footer className="border-t border-slate-200 bg-slate-50 py-10 text-sm text-slate-600">
      <div className="mx-auto grid max-w-6xl gap-6 px-4 sm:grid-cols-4">
        <div>
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-slate-900 text-xs font-bold text-white">
              AEC
            </div>
            <span className="font-semibold text-slate-900">AEC Platform</span>
          </div>
          <p className="mt-3 text-xs">
            Nền tảng AI quản lý dự án xây dựng dành riêng cho Việt Nam.
          </p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-900">
            Sản phẩm
          </p>
          <ul className="mt-3 space-y-1.5 text-xs">
            <li><Link href="/pricing" className="hover:text-slate-900">Gói cước</Link></li>
            <li><Link href="/signup" className="hover:text-slate-900">Đăng ký</Link></li>
            <li><Link href="/login" className="hover:text-slate-900">Đăng nhập</Link></li>
          </ul>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-900">
            Hỗ trợ
          </p>
          <ul className="mt-3 space-y-1.5 text-xs">
            <li><a href="mailto:support@aec-platform.vn" className="hover:text-slate-900"><Mail size={11} className="mr-1 inline" />support@</a></li>
            <li><a href="mailto:sales@aec-platform.vn" className="hover:text-slate-900"><Phone size={11} className="mr-1 inline" />sales@</a></li>
          </ul>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-900">
            Pháp lý
          </p>
          <ul className="mt-3 space-y-1.5 text-xs">
            <li><span className="text-slate-500"><Shield size={11} className="mr-1 inline" />Bảo mật dữ liệu</span></li>
            <li><span className="text-slate-500"><Layers size={11} className="mr-1 inline" />Điều khoản dịch vụ</span></li>
          </ul>
        </div>
      </div>
      <div className="mx-auto mt-8 max-w-6xl border-t border-slate-200 px-4 pt-6 text-xs text-slate-500">
        © {new Date().getFullYear()} AEC Platform. Mọi quyền được bảo lưu.
      </div>
    </footer>
  );
}
