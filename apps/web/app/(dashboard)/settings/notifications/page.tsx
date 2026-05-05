"use client";

/**
 * Per-user notification preferences page.
 *
 * One row per known alert kind, with two channel switches (email,
 * Slack). Server pre-fills the response with every key in the
 * `_KNOWN_PREF_KEYS` allowlist so the UI doesn't need to know the
 * list — drop in a new alert kind on the server, the next page load
 * surfaces it here automatically.
 *
 * Strings flow through `next-intl` so a future admin who flips the
 * dashboard locale to English gets the same UX as the supplier portal
 * already has. Keys live under the `settings_notifications` namespace
 * in `apps/web/i18n/messages/{vi,en}.json`.
 */

import { useTranslations } from "next-intl";

import { usePreferences, useUpsertPreference } from "@/hooks/notifications";

export default function NotificationPreferencesPage(): JSX.Element {
  const t = useTranslations("settings_notifications");
  const tAlerts = useTranslations("settings_notifications.alerts");
  const { data, isLoading, error } = usePreferences();
  const upsert = useUpsertPreference();

  // Look up the localised copy for an alert kind. When the server
  // returns a key the i18n bundle doesn't have copy for (an
  // experimental alert ahead of a translation pass), we fall back to
  // the raw key so the row still renders something meaningful.
  function alertCopy(key: string): { title: string; description: string } {
    const titleKey = `${key}.title` as const;
    const descKey = `${key}.description` as const;
    try {
      return {
        title: tAlerts(titleKey),
        description: tAlerts(descKey),
      };
    } catch {
      return { title: key, description: "" };
    }
  }

  return (
    <div className="mx-auto max-w-3xl p-6">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">{t("title")}</h1>
        <p className="mt-1 text-sm text-slate-500">{t("description")}</p>
      </header>

      {isLoading ? (
        <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">
          {t("loading")}
        </div>
      ) : error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-700">
          {(error as Error).message}
        </div>
      ) : (
        <ul className="divide-y divide-slate-100 overflow-hidden rounded-lg border border-slate-200 bg-white">
          {(data ?? []).map((pref) => {
            const copy = alertCopy(pref.key);
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
                    label={t("label_email")}
                    checked={pref.email_enabled}
                    onChange={(next) =>
                      upsert.mutate({ key: pref.key, email_enabled: next })
                    }
                    disabled={upsert.isPending}
                  />
                  <ToggleSwitch
                    label={t("label_slack")}
                    checked={pref.slack_enabled}
                    onChange={(next) =>
                      upsert.mutate({ key: pref.key, slack_enabled: next })
                    }
                    disabled={upsert.isPending}
                    tooltip={t("slack_tooltip")}
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
