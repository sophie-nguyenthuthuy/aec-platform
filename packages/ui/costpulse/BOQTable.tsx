"use client";

import { useMemo, useState } from "react";
import type { BoqItem, BoqItemInput } from "@aec/types";

import { cn } from "../lib/cn";
import { Input } from "../primitives/input";
import { Button } from "../primitives/button";
import { formatVnd, formatNumber } from "./formatters";

interface BOQTableProps {
  items: BoqItem[];
  editable?: boolean;
  onChange?: (items: BoqItemInput[]) => void;
  onMaterialLookup?: (materialCode: string) => void;
  className?: string;
}

interface Node {
  item: BoqItem;
  children: Node[];
}

function buildTree(items: BoqItem[]): Node[] {
  const byId = new Map<string, Node>();
  const roots: Node[] = [];
  const sorted = [...items].sort((a, b) => a.sort_order - b.sort_order);
  for (const it of sorted) {
    byId.set(it.id, { item: it, children: [] });
  }
  for (const node of byId.values()) {
    const parentId = node.item.parent_id;
    if (parentId && byId.has(parentId)) {
      byId.get(parentId)!.children.push(node);
    } else {
      roots.push(node);
    }
  }
  return roots;
}

export function BOQTable({
  items,
  editable = false,
  onChange,
  onMaterialLookup,
  className,
}: BOQTableProps): JSX.Element {
  const [draft, setDraft] = useState<Record<string, Partial<BoqItem>>>({});
  const tree = useMemo(() => buildTree(items), [items]);

  function emitChange(updated: Record<string, Partial<BoqItem>>) {
    setDraft(updated);
    if (!onChange) return;
    onChange(
      items.map((it) => {
        const patch = updated[it.id] ?? {};
        return { ...it, ...patch };
      }),
    );
  }

  function updateField<K extends keyof BoqItem>(id: string, field: K, value: BoqItem[K]) {
    emitChange({ ...draft, [id]: { ...draft[id], [field]: value } });
  }

  const cellsHeader = (
    <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-600">
      <th className="w-24 px-3 py-2">Code</th>
      <th className="px-3 py-2">Description</th>
      <th className="w-20 px-3 py-2">Unit</th>
      <th className="w-28 px-3 py-2 text-right">Qty</th>
      <th className="w-40 px-3 py-2 text-right">Unit price (VND)</th>
      <th className="w-44 px-3 py-2 text-right">Total (VND)</th>
    </tr>
  );

  const renderRows = (nodes: Node[], depth: number): JSX.Element[] =>
    nodes.flatMap((node) => {
      const { item, children } = node;
      const isGroup = children.length > 0;
      const patch = draft[item.id] ?? {};
      const qty = (patch.quantity ?? item.quantity) as string | null;
      const unitPrice = (patch.unit_price_vnd ?? item.unit_price_vnd) as string | null;
      const total =
        qty && unitPrice ? Number(qty) * Number(unitPrice) : item.total_price_vnd;

      const row = (
        <tr
          key={item.id}
          className={cn(
            "border-b border-slate-100 text-sm",
            isGroup && "bg-slate-50 font-semibold text-slate-900",
          )}
        >
          <td className="px-3 py-2 text-slate-500">{item.code ?? ""}</td>
          <td className="px-3 py-2" style={{ paddingLeft: `${depth * 20 + 12}px` }}>
            {item.description}
            {item.material_code && (
              <button
                type="button"
                onClick={() => onMaterialLookup?.(item.material_code!)}
                className="ml-2 text-xs text-sky-600 hover:underline"
              >
                {item.material_code}
              </button>
            )}
          </td>
          <td className="px-3 py-2 text-slate-600">{item.unit ?? ""}</td>
          <td className="px-3 py-2 text-right">
            {editable && !isGroup ? (
              <Input
                type="number"
                value={qty ?? ""}
                onChange={(e) => updateField(item.id, "quantity", e.target.value || null)}
                className="h-7 text-right text-sm"
              />
            ) : (
              formatNumber(qty, 2)
            )}
          </td>
          <td className="px-3 py-2 text-right">
            {editable && !isGroup ? (
              <Input
                type="number"
                value={unitPrice ?? ""}
                onChange={(e) => updateField(item.id, "unit_price_vnd", e.target.value || null)}
                className="h-7 text-right text-sm"
              />
            ) : (
              formatVnd(unitPrice)
            )}
          </td>
          <td className="px-3 py-2 text-right font-medium">{formatVnd(total)}</td>
        </tr>
      );

      return [row, ...renderRows(children, depth + 1)];
    });

  return (
    <div className={cn("overflow-hidden rounded-lg border border-slate-200", className)}>
      <table className="w-full">
        <thead>{cellsHeader}</thead>
        <tbody>{renderRows(tree, 0)}</tbody>
      </table>
      {editable && (
        <div className="flex justify-end border-t border-slate-200 bg-slate-50 px-3 py-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => emitChange({})}
            disabled={Object.keys(draft).length === 0}
          >
            Reset changes
          </Button>
        </div>
      )}
    </div>
  );
}
