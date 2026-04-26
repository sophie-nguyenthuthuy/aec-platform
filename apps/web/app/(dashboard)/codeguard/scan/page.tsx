"use client";

import { useState } from "react";
import { Info } from "lucide-react";
import { ComplianceScore, FindingItem } from "@aec/ui/codeguard";
import type { ScanResponse, RegulationCategory } from "@aec/ui/codeguard";
import { useCodeguardScan, type ProjectParameters } from "@/hooks/codeguard";

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
  const [result, setResult] = useState<ScanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const scan = useCodeguardScan();

  const runScan = async () => {
    if (!projectId) return;
    // Mirror the query page's error-handling shape: catch the rejection,
    // store the message, and still advance to the results step so the
    // user sees feedback instead of being stranded in the review step
    // with isPending=false and no signal that anything happened.
    setError(null);
    try {
      const res = await scan.mutateAsync({ project_id: projectId, parameters: params, categories });
      setResult(res);
      setStep("results");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Đã xảy ra lỗi";
      setError(message);
      setStep("results");
    }
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
              disabled={scan.isPending}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {scan.isPending ? "Đang quét..." : "Bắt đầu quét"}
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
            </div>
          ) : result ? (
            <>
              <div className="rounded-xl border border-slate-200 bg-white p-6">
                <h3 className="mb-4 font-semibold">Kết quả tổng hợp</h3>
                <ComplianceScore pass={result.pass_count} warn={result.warn_count} fail={result.fail_count} />
              </div>
              <div className="space-y-3">
                {/*
                  Empty-findings disambiguation: total === 0 means the
                  scan returned zero findings — could be (a) the LLM had
                  nothing to flag (clean scan) OR (b) retrieval surfaced
                  no relevant chunks for the chosen categories. We can't
                  distinguish from the response shape alone, so we use
                  the same amber "advisory" treatment as the query
                  page's abstain card rather than a bland slate "all
                  clear" message that could mislead the user.
                */}
                {result.findings.length === 0 ? (
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
                ) : (
                  result.findings.map((f, i) => <FindingItem key={i} finding={f} />)
                )}
              </div>
            </>
          ) : null}
          <button
            type="button"
            onClick={() => {
              setStep("params");
              setResult(null);
              setError(null);
            }}
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm"
          >
            Quét lại
          </button>
        </div>
      )}
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
