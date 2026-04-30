"use client";

/**
 * Per-user notification preferences page.
 *
 * One row per known alert kind, with two channel switches (email,
 * Slack). Server pre-fills the response with every key in the
 * `_KNOWN_PREF_KEYS` allowlist so the UI doesn't need to know the
 * list — drop in a new alert kind on the server, the next page load
 * surfaces it here automatically.
 */

import { usePreferences, useUpsertPreference } from "@/hooks/notifications";

// User-facing copy keyed off the server's `key` discriminator. Adding
// a new alert kind: append to the server's `_KNOWN_PREF_KEYS` AND add
// an entry here. If the server returns a key we don't have copy for
// (e.g. an experimental alert shipped to a single org), we fall back
// to the raw key so the row still renders.
const ALERT_COPY: Record<string, { title: string; description: string }> = {
  scraper_drift: {
    title: "Cảnh báo trôi dữ liệu giá",
    description:
      "Nhận email khi tỷ lệ vật tư không khớp tăng cao bất thường — dấu hiệu sớm rằng sở Xây dựng đã đổi cách đặt tên.",
  },
  rfq_deadline_summary: {
    title: "Tổng kết hạn báo giá",
    description:
      "Email tổng hợp hằng ngày các RFQ sắp hết hạn và những nhà cung cấp chưa phản hồi.",
  },
  weekly_digest_email: {
    title: "Bản tin tuần",
    description:
      "Tóm tắt hoạt động tuần qua các dự án bạn đang theo dõi.",
  },
};

export default function NotificationPreferencesPage(): JSX.Element {
  const { data, isLoading, error } = usePreferences();
  const upsert = useUpsertPreference();

  return (
    <div className="mx-auto max-w-3xl p-6">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Thông báo</h1>
        <p className="mt-1 text-sm text-slate-500">
          Chọn các cảnh báo bạn muốn nhận qua email hoặc Slack. Cài đặt áp dụng riêng cho tổ chức hiện tại.
        </p>
      </header>

      {isLoading ? (
        <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">
          Đang tải…
        </div>
      ) : error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-700">
          {(error as Error).message}
        </div>
      ) : (
        <ul className="divide-y divide-slate-100 overflow-hidden rounded-lg border border-slate-200 bg-white">
          {(data ?? []).map((pref) => {
            const copy = ALERT_COPY[pref.key] ?? {
              title: pref.key,
              description: "",
            };
            return (
              <li key={pref.key} className="flex items-start justify-between gap-4 px-4 py-4">
                <div className="flex-1">
                  <div className="text-sm font-semibold text-slate-900">{copy.title}</div>
                  {copy.description ? (
                    <p className="mt-1 text-xs text-slate-600">{copy.description}</p>
                  ) : null}
                </div>
                <div className="flex items-center gap-4">
                  <ToggleSwitch
                    label="Email"
                    checked={pref.email_enabled}
                    onChange={(next) =>
                      upsert.mutate({ key: pref.key, email_enabled: next })
                    }
                    disabled={upsert.isPending}
                  />
                  <ToggleSwitch
                    label="Slack"
                    checked={pref.slack_enabled}
                    onChange={(next) =>
                      upsert.mutate({ key: pref.key, slack_enabled: next })
                    }
                    // Slack delivery isn't actually implemented yet on the server side;
                    // disable the switch with a tooltip to set expectations rather
                    // than letting users toggle a no-op.
                    disabled={upsert.isPending || true}
                    tooltip="Sắp ra mắt"
                  />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}


function ToggleSwitch({
  label,
  checked,
  onChange,
  disabled,
  tooltip,
}: {
  label: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  tooltip?: string;
}): JSX.Element {
  return (
    <label
      className={`flex items-center gap-2 text-xs ${
        disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer"
      }`}
      title={tooltip}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        disabled={disabled}
        className="h-4 w-4 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
      />
      <span className="font-medium text-slate-700">{label}</span>
    </label>
  );
}
