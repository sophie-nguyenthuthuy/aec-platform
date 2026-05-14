import type { Metadata } from "next";

/**
 * Static offline fallback. Served by the service worker when a
 * navigation request fails (network error, captive portal, airplane
 * mode). Kept route-handler-free + dependency-free so the SW can
 * actually cache it without a JS bundle that would itself fail to
 * load offline.
 */
export const metadata: Metadata = {
  title: "Mất kết nối — AEC Platform",
};

export default function OfflinePage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-slate-50 px-6 py-12">
      <div className="max-w-md rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-amber-100">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-amber-700">
            <path d="M1 1l22 22" />
            <path d="M16.72 11.06A10.94 10.94 0 0119 12.55" />
            <path d="M5 12.55a10.94 10.94 0 015.17-2.39" />
            <path d="M10.71 5.05A16 16 0 0122.58 9" />
            <path d="M1.42 9a15.91 15.91 0 014.7-2.88" />
            <path d="M8.53 16.11a6 6 0 016.95 0" />
            <path d="M12 20h.01" />
          </svg>
        </div>
        <h1 className="text-xl font-semibold text-slate-900">
          Đang mất kết nối mạng
        </h1>
        <p className="mt-2 text-sm text-slate-600">
          Trang này chưa thể tải vì điện thoại / máy tính đang offline.
          Khi mạng có lại, mở lại app — dữ liệu đã chỉnh sửa sẽ tự đồng bộ.
        </p>
        <p className="mt-4 text-xs text-slate-500">
          Nếu bạn đang ở công trường có sóng yếu, thử di chuyển ra chỗ
          thoáng hoặc dùng wifi văn phòng nhà thầu.
        </p>
        <button
          onClick={() => location.reload()}
          className="mt-6 inline-flex items-center gap-1 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          type="button"
        >
          Thử lại
        </button>
      </div>
    </main>
  );
}
