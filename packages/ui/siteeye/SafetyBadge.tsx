import type { IncidentSeverity, SafetyStatus } from "./types";

const SAFETY_STYLES: Record<SafetyStatus, string> = {
  clear: "bg-green-100 text-green-800 border-green-200",
  warning: "bg-amber-100 text-amber-800 border-amber-200",
  critical: "bg-red-100 text-red-800 border-red-200",
};

const SEVERITY_STYLES: Record<IncidentSeverity, string> = {
  low: "bg-gray-100 text-gray-800 border-gray-200",
  medium: "bg-amber-100 text-amber-800 border-amber-200",
  high: "bg-orange-100 text-orange-800 border-orange-200",
  critical: "bg-red-100 text-red-800 border-red-200",
};

export function SafetyBadge({ status }: { status: SafetyStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${SAFETY_STYLES[status]}`}
    >
      {status}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: IncidentSeverity }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${SEVERITY_STYLES[severity]}`}
    >
      {severity}
    </span>
  );
}
