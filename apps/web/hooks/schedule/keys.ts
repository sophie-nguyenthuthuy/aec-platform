export const scheduleKeys = {
  all: ["schedule"] as const,
  lists: (filters: object = {}) => ["schedule", "lists", filters] as const,
  detail: (id: string) => ["schedule", "detail", id] as const,
  riskAssessments: (id: string) => ["schedule", "risk-assessments", id] as const,
} as const;
