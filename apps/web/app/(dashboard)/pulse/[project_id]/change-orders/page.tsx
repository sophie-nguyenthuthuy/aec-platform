"use client";
import { useParams } from "next/navigation";
import { ChangeOrderCard } from "@aec/ui/pulse";

import { ResourceAuditPanel } from "@/components/ResourceAuditPanel";

import {
  useAnalyzeChangeOrder,
  useApproveChangeOrder,
  useChangeOrders,
} from "../../../../../hooks/pulse/useChangeOrders";

export default function PulseChangeOrdersPage() {
  const params = useParams<{ project_id: string }>();
  const projectId = params.project_id;

  const cosQ = useChangeOrders({ project_id: projectId, limit: 100 });
  const analyze = useAnalyzeChangeOrder();
  const approve = useApproveChangeOrder();

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Change Orders</h2>

      {cosQ.isLoading && <p>Loading…</p>}
      {!cosQ.isLoading && (cosQ.data ?? []).length === 0 && (
        <p className="text-muted-foreground">No change orders yet.</p>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        {(cosQ.data ?? []).map((co) => (
          <div key={co.id} className="space-y-2">
            <ChangeOrderCard
              changeOrder={co}
              analyzing={analyze.isPending && analyze.variables === co.id}
              onAnalyze={(id) => analyze.mutate(id)}
              onApprove={(id, decision) =>
                approve.mutate({ id, decision: { decision } })
              }
            />
            {/* Per-CO audit drilldown — answers "who approved this CO?"
                without leaving the page. Renders nothing for non-admin
                viewers and nothing when there's no audit history. */}
            <ResourceAuditPanel
              resourceType="change_orders"
              resourceId={co.id}
              limit={5}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
