interface Props {
  phaseProgress: Record<string, number>;
}

const PHASE_ORDER = [
  "site_prep",
  "foundation",
  "structure",
  "envelope",
  "mep",
  "finishes",
  "exterior",
  "handover",
];

const PHASE_LABEL: Record<string, string> = {
  site_prep: "Site prep",
  foundation: "Foundation",
  structure: "Structure",
  envelope: "Envelope",
  mep: "MEP",
  finishes: "Finishes",
  exterior: "Exterior",
  handover: "Handover",
};

export function PhaseBar({ phaseProgress }: Props) {
  const entries = PHASE_ORDER.filter((p) => p in phaseProgress).map((p) => [
    p,
    phaseProgress[p] ?? 0,
  ]) as Array<[string, number]>;

  if (entries.length === 0) {
    return (
      <p className="text-sm text-gray-500">No phase-level data yet.</p>
    );
  }

  return (
    <div className="space-y-2">
      {entries.map(([phase, pct]) => (
        <div key={phase}>
          <div className="mb-1 flex justify-between text-xs">
            <span className="text-gray-700">{PHASE_LABEL[phase] ?? phase}</span>
            <span className="text-gray-500">{pct.toFixed(0)}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded bg-gray-100">
            <div
              className="h-full bg-sky-500"
              style={{ width: `${Math.min(pct, 100)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
