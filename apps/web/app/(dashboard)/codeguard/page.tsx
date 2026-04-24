import Link from "next/link";
import { FileCheck, FileText, ListChecks, MessageSquare } from "lucide-react";

const TILES = [
  {
    href: "/codeguard/query",
    title: "Hỏi quy chuẩn",
    description: "Đặt câu hỏi tự nhiên, nhận trả lời kèm trích dẫn điều khoản cụ thể.",
    icon: MessageSquare,
  },
  {
    href: "/codeguard/scan",
    title: "Quét tuân thủ",
    description: "Rà soát thông số dự án so với quy chuẩn, phát hiện vi phạm và cảnh báo.",
    icon: FileCheck,
  },
  {
    href: "/codeguard/checklist",
    title: "Checklist cấp phép",
    description: "Sinh danh sách hồ sơ cần thiết theo địa phương và loại công trình.",
    icon: ListChecks,
  },
  {
    href: "/codeguard/regulations",
    title: "Thư viện quy chuẩn",
    description: "Tra cứu QCVN, TCVN, luật xây dựng và các văn bản pháp quy.",
    icon: FileText,
  },
] as const;

export default function CodeguardHomePage() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">CODEGUARD</h2>
        <p className="text-sm text-slate-600">
          Trợ lý AI về quy chuẩn xây dựng và quy hoạch Việt Nam.
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {TILES.map((t) => {
          const Icon = t.icon;
          return (
            <Link
              key={t.href}
              href={t.href}
              className="group rounded-xl border border-slate-200 bg-white p-6 transition hover:border-blue-400 hover:shadow-sm"
            >
              <Icon className="mb-3 text-blue-600" size={24} />
              <h3 className="font-semibold text-slate-900 group-hover:text-blue-700">{t.title}</h3>
              <p className="mt-1 text-sm text-slate-600">{t.description}</p>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
