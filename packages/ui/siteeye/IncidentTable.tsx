import type { SafetyIncident, UUID } from "./types";
import { SeverityBadge } from "./SafetyBadge";

interface Props {
  incidents: SafetyIncident[];
  onAcknowledge?: (id: UUID) => void;
  onResolve?: (id: UUID) => void;
}

const TYPE_LABEL: Record<string, string> = {
  no_ppe: "Missing PPE",
  unsafe_scaffold: "Unsafe scaffold",
  open_trench: "Open trench",
  fire_hazard: "Fire hazard",
  electrical_hazard: "Electrical hazard",
};

export function IncidentTable({ incidents, onAcknowledge, onResolve }: Props) {
  if (incidents.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-gray-200 p-6 text-center text-sm text-gray-500">
        No safety incidents in this range.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 text-left text-xs uppercase text-gray-500">
          <tr>
            <th className="px-3 py-2">Detected</th>
            <th className="px-3 py-2">Type</th>
            <th className="px-3 py-2">Severity</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2">Description</th>
            <th className="px-3 py-2"></th>
          </tr>
        </thead>
        <tbody>
          {incidents.map((i) => (
            <tr key={i.id} className="border-t border-gray-100">
              <td className="px-3 py-2 text-gray-600">
                {new Date(i.detected_at).toLocaleString()}
              </td>
              <td className="px-3 py-2">
                {TYPE_LABEL[i.incident_type] ?? i.incident_type}
              </td>
              <td className="px-3 py-2">
                <SeverityBadge severity={i.severity} />
              </td>
              <td className="px-3 py-2 capitalize text-gray-700">{i.status}</td>
              <td className="px-3 py-2 text-gray-700">{i.ai_description}</td>
              <td className="px-3 py-2">
                <div className="flex gap-2">
                  {i.status === "open" ? (
                    <button
                      type="button"
                      onClick={() => onAcknowledge?.(i.id)}
                      className="rounded border border-gray-300 px-2 py-1 text-xs"
                    >
                      Acknowledge
                    </button>
                  ) : null}
                  {i.status !== "resolved" ? (
                    <button
                      type="button"
                      onClick={() => onResolve?.(i.id)}
                      className="rounded bg-emerald-600 px-2 py-1 text-xs font-medium text-white"
                    >
                      Resolve
                    </button>
                  ) : null}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
