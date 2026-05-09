"use client";

import { useState } from "react";
import { CheckCircle2, Info, Loader2 } from "lucide-react";
import { ComplianceScore, FindingItem } from "@aec/ui/codeguard";
import type { Finding, RegulationCategory } from "@aec/ui/codeguard";
import {
  useCodeguardScanStream,
  type ProjectParameters,
  type ScanDonePayload,
} from "@/hooks/codeguard";

const CATEGORIES: Array<{ value: RegulationCategory; label: string }> = [
  { value: "fire_safety", label: "PCCC" },
  { value: "accessibility", label: "Tiếp cận" },
  { value: "structure", label: "Kết cấu" },
  { value: "zoning", label: "Quy hoạch" },
  { value: "energy", label: "Năng lượng" },
];

type Step = "params" | "review" | "results";

export default function ComplianceScanWizardPage() {
  const [step, setStep] = useState<Step>("params");
  const [projectId, setProjectId] = useState("");
  const [params, setParams] = useState<ProjectParameters>({ project_type: "residential" });
  const [categories, setCategories] = useState<RegulationCategory[]>(
    CATEGORIES.map((c) => c.value),
  );

  // Streaming-aware state. Findings accumulate as `category_done` events
  // arrive; `done` carries the aggregate counts that drive the donut.
  // Per-category status drives the in-flight progress list.
  const [streaming, setStreaming] = useState(false);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [done, setDone] = useState<ScanDonePayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Optional deep-link surfaced from the error envelope's `details_url`.
  // Currently only the cap-check 429 sets this (→ /codeguard/quota);
  // for stream-internal errors it stays null and the error card omits
  // the CTA.
  const [errorDetailsUrl, setErrorDetailsUrl] = useState<string | null>(null);
  const [categoryStatus, setCategoryStatus] = useState<
    Record<string, "pending" | "in_progress" | "done">
  >({});

  const startStream = useCodeguardScanStream();

  const runScan = async () => {
    if (!projectId) return;

    // Reset accumulated state so a re-run from "Quét lại" starts clean.
    setFindings([]);
    setDone(null);
    setError(null);
    setErrorDetailsUrl(null);
    // Seed every selected category as `pending` so the progress list
    // shows the full slate immediately — categories flip to in_progress
    // and then done as their events arrive.
    setCategoryStatus(
      Object.fromEntries(categories.map((c) => [c, "pending" as const])),
    );
    setStreaming(true);
    setStep("results");

    await startStream(
      { project_id: projectId, parameters: params, categories },
      {
        onCategoryStart: (cat) => {
          setCategoryStatus((s) => ({ ...s, [cat]: "in_progress" }));
        },
        onCategoryDone: (payload) => {
          setCategoryStatus((s) => ({ ...s, [payload.category]: "done" }));
          if (payload.findings.length > 0) {
            setFindings((curr) => [...curr, ...payload.findings]);
          }
        },
        onDone: (payload) => {
          setDone(payload);
        },
        onError: ({ message, detailsUrl }) => {
          setError(message);
          setErrorDetailsUrl(detailsUrl ?? null);
        },
      },
    );
    setStreaming(false);
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Quét tuân thủ quy chuẩn</h2>
        <p className="text-sm text-slate-600">Nhập thông số dự án để hệ thống rà soát tự động.</p>
      </div>

      <Stepper current={step} />

      {step === "params" && (
        <div className="grid gap-4 rounded-xl border border-slate-200 bg-white p-6 md:grid-cols-2">
          <LabeledInput label="Mã dự án" value={projectId} onChange={setProjectId} placeholder="UUID" required />
          <LabeledSelect
            label="Loại công trình"
            value={params.project_type}
            onChange={(v) => setParams({ ...params, project_type: v })}
            options={[
              { value: "residential", label: "Nhà ở" },
              { value: "commercial", label: "Thương mại" },
              { value: "mixed_use", label: "Hỗn hợp" },
              { value: "industrial", label: "Công nghiệp" },
              { value: "public", label: "Công cộng" },
            ]}
          />
          <LabeledNumber
            label="Tổng diện tích (m²)"
            value={params.total_area_m2}
            onChange={(v) => setParams({ ...params, total_area_m2: v })}
          />
          <LabeledNumber
            label="Chiều cao tối đa (m)"
            value={params.max_height_m}
            onChange={(v) => setParams({ ...params, max_height_m: v })}
          />
          <LabeledNumber
            label="Số tầng trên mặt đất"
            value={params.floors_above}
            onChange={(v) => setParams({ ...params, floors_above: v })}
          />
          <LabeledNumber
            label="Số tầng hầm"
            value={params.floors_below}
            onChange={(v) => setParams({ ...params, floors_below: v })}
          />
          <LabeledNumber
            label="Sức chứa (người)"
            value={params.occupancy}
            onChange={(v) => setParams({ ...params, occupancy: v })}
          />
          <LabeledInput
            label="Tỉnh / Thành"
            value={(params.location?.province as string) ?? ""}
            onChange={(v) => setParams({ ...params, location: { ...params.location, province: v } })}
          />

          <div className="md:col-span-2">
            <div className="mb-1 text-sm font-medium text-slate-700">Hạng mục cần quét</div>
            <div className="flex flex-wrap gap-2">
              {CATEGORIES.map((c) => {
                const selected = categories.includes(c.value);
                return (
                  <button
                    key={c.value}
                    type="button"
                    aria-pressed={selected}
                    onClick={() =>
                      setCategories((s) =>
                        selected ? s.filter((x) => x !== c.value) : [...s, c.value],
                      )
                    }
                    className={`rounded-full border px-3 py-1 text-xs ${
                      selected
                        ? "border-blue-500 bg-blue-50 text-blue-700"
                        : "border-slate-300 bg-white text-slate-600"
                    }`}
                  >
                    {c.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="md:col-span-2 flex justify-end">
            <button
              type="button"
              onClick={() => setStep("review")}
              disabled={!projectId}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              Tiếp tục
            </button>
          </div>
        </div>
      )}

      {step === "review" && (
        <div className="rounded-xl border border-slate-200 bg-white p-6">
          <h3 className="mb-3 font-semibold">Xác nhận thông số</h3>
          <pre className="overflow-x-auto rounded bg-slate-50 p-3 text-xs text-slate-800">
            {JSON.stringify({ project_id: projectId, parameters: params, categories }, null, 2)}
          </pre>
          <div className="mt-4 flex justify-between">
            <button
              type="button"
              onClick={() => setStep("params")}
              className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm"
            >
              Quay lại
            </button>
            <button
              type="button"
              onClick={runScan}
              disabled={streaming}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {streaming ? "Đang quét..." : "Bắt đầu quét"}
            </button>
          </div>
        </div>
      )}

      {step === "results" && (
        <div className="space-y-4">
          {error ? (
            <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-800">
              <div className="mb-1 font-medium">Lỗi khi quét tuân thủ</div>
              <p>{error}</p>
              {errorDetailsUrl && (
                <div className="mt-3">
                  <a
                    href={errorDetailsUrl}
                    className="inline-flex items-center gap-1 rounded-md border border-red-300 bg-white px-3 py-1.5 text-xs font-medium text-red-900 hover:bg-red-50"
                  >
                    Xem hạn mức
                  </a>
                </div>
              )}
            </div>
          ) : (
            <>
              {/*
                Per-category progress strip. Always rendered — during the
                stream it shows the live status, and after `done` it
                stays as a record of which categories actually got
                scanned (useful when one or more had no retrieval).
              */}
              <CategoryProgress status={categoryStatus} />

              {/*
                Aggregate ComplianceScore donut. Renders only after the
                terminal `done` event arrives because it needs aggregate
                counts (pass/warn/fail). During streaming the per-finding
                cards below give the user incremental feedback.
              */}
              {done && (
                <div className="rounded-xl border border-slate-200 bg-white p-6">
                  <h3 className="mb-4 font-semibold">Kết quả tổng hợp</h3>
                  <ComplianceScore
                    pass={done.pass_count}
                    warn={done.warn_count}
                    fail={done.fail_count}
                  />
                </div>
              )}

              <div className="space-y-3">
                {/*
                  During streaming, render findings as they arrive.
                  After the terminal `done`, we know whether the empty-
                  findings advisory is the correct treatment (total ===
                  0). While streaming we deliberately don't show the
                  advisory yet — categories that haven't reported in
                  could still produce findings.
                */}
                {findings.map((f, i) => (
                  <FindingItem key={i} finding={f} />
                ))}
                {done && findings.length === 0 && (
                  <div className="rounded-xl border border-amber-200 bg-amber-50 p-6 text-sm text-amber-900">
                    <div className="mb-1 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-amber-700">
                      <Info size={14} />
                      Không có vấn đề nào được nêu
                    </div>
                    <p>
                      Hệ thống không tìm thấy vấn đề tuân thủ nào với các hạng mục đã chọn.
                      Hãy kiểm tra xem các quy chuẩn liên quan đã được nạp vào CODEGUARD chưa.
                    </p>
                  </div>
                )}
              </div>
            </>
          )}
          <button
            type="button"
            onClick={() => {
              setStep("params");
              setFindings([]);
              setDone(null);
              setError(null);
              setCategoryStatus({});
            }}
            disabled={streaming}
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm disabled:opacity-50"
          >
            Quét lại
          </button>
        </div>
      )}
    </div>
  );
}

function CategoryProgress({
  status,
}: {
  status: Record<string, "pending" | "in_progress" | "done">;
}) {
  // Render in the same order CATEGORIES is declared so the strip's
  // visual order matches the user's selection UI from the params step.
  const rows = CATEGORIES.filter((c) => status[c.value] !== undefined);
  if (rows.length === 0) return null;

  return (
    <div
      role="region"
      aria-label="Tiến độ quét theo hạng mục"
      aria-live="polite"
      className="rounded-xl border border-slate-200 bg-white p-4"
    >
      <ol className="divide-y divide-slate-100">
        {rows.map((c) => {
          const s = status[c.value];
          return (
            <li
              key={c.value}
              data-testid={`category-status-${c.value}`}
              className="flex items-center gap-3 py-2 text-sm"
            >
              {s === "done" ? (
                <CheckCircle2 size={16} className="shrink-0 text-emerald-600" />
              ) : s === "in_progress" ? (
                <Loader2 size={16} className="shrink-0 animate-spin text-blue-600" />
              ) : (
                <span className="inline-block h-3 w-3 shrink-0 rounded-full border border-slate-300" />
              )}
              <span className="flex-1 text-slate-700">{c.label}</span>
              <span className="text-xs text-slate-500">
                {s === "done" ? "Xong" : s === "in_progress" ? "Đang quét" : "Chờ"}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function Stepper({ current }: { current: Step }) {
  const steps: Array<{ key: Step; label: string }> = [
    { key: "params", label: "1. Thông số" },
    { key: "review", label: "2. Xác nhận" },
    { key: "results", label: "3. Kết quả" },
  ];
  return (
    <ol className="flex items-center gap-2 text-sm">
      {steps.map((s, i) => (
        <li key={s.key} className="flex items-center gap-2">
          <span
            className={`rounded-full px-3 py-1 ${
              current === s.key
                ? "bg-blue-600 text-white"
                : "bg-slate-200 text-slate-600"
            }`}
          >
            {s.label}
          </span>
          {i < steps.length - 1 && <span className="text-slate-400">→</span>}
        </li>
      ))}
    </ol>
  );
}

function LabeledInput(props: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  required?: boolean;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-700">
        {props.label}
        {props.required && <span className="ml-1 text-red-500">*</span>}
      </span>
      <input
        type="text"
        value={props.value}
        placeholder={props.placeholder}
        onChange={(e) => props.onChange(e.target.value)}
        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
      />
    </label>
  );
}

function LabeledNumber(props: {
  label: string;
  value: number | undefined;
  onChange: (v: number | undefined) => void;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-700">{props.label}</span>
      <input
        type="number"
        value={props.value ?? ""}
        onChange={(e) =>
          props.onChange(e.target.value === "" ? undefined : Number(e.target.value))
        }
        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
      />
    </label>
  );
}

function LabeledSelect(props: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: Array<{ value: string; label: string }>;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-700">{props.label}</span>
      <select
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
      >
        {props.options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
