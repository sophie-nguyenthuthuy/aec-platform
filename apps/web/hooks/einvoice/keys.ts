export const einvoiceKeys = {
  all: ["einvoice"] as const,
  invoices: (filters: object) => ["einvoice", "invoices", filters] as const,
  invoice: (id: string) => ["einvoice", "invoice", id] as const,
  mst: (mst: string) => ["einvoice", "mst", mst] as const,
};
