"use client";
import { useState } from "react";
import { GripVertical, Plus, Trash2 } from "lucide-react";
import type { ScopeItem } from "@aec/types/winwork";

import { Button } from "../primitives/button";
import { Input } from "../primitives/input";
import { Textarea } from "../primitives/textarea";
import { Label } from "../primitives/label";

const PHASES = [
  "Concept",
  "Schematic",
  "Design Development",
  "Construction Documents",
  "Construction Administration",
] as const;

interface ScopeBuilderProps {
  items: ScopeItem[];
  onChange: (items: ScopeItem[]) => void;
}

export function ScopeBuilder({ items, onChange }: ScopeBuilderProps) {
  const [dragIdx, setDragIdx] = useState<number | null>(null);

  function update(idx: number, patch: Partial<ScopeItem>) {
    onChange(items.map((item, i) => (i === idx ? { ...item, ...patch } : item)));
  }

  function remove(idx: number) {
    onChange(items.filter((_, i) => i !== idx));
  }

  function add() {
    onChange([
      ...items,
      {
        id: crypto.randomUUID(),
        phase: "Concept",
        title: "New deliverable",
        deliverables: [],
      },
    ]);
  }

  function onDragStart(idx: number) {
    setDragIdx(idx);
  }

  function onDrop(targetIdx: number) {
    if (dragIdx === null || dragIdx === targetIdx) return;
    const next = [...items];
    const [moved] = next.splice(dragIdx, 1);
    next.splice(targetIdx, 0, moved!);
    onChange(next);
    setDragIdx(null);
  }

  return (
    <div className="space-y-3">
      {items.map((item, idx) => (
        <div
          key={item.id}
          draggable
          onDragStart={() => onDragStart(idx)}
          onDragOver={(e) => e.preventDefault()}
          onDrop={() => onDrop(idx)}
          className="flex gap-3 rounded-md border p-3"
        >
          <GripVertical className="mt-2 h-4 w-4 cursor-grab text-muted-foreground" />
          <div className="flex-1 space-y-2">
            <div className="flex gap-2">
              <select
                className="h-9 rounded-md border border-input bg-background px-2 text-sm"
                value={item.phase}
                onChange={(e) => update(idx, { phase: e.target.value })}
              >
                {PHASES.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
              <Input
                value={item.title}
                onChange={(e) => update(idx, { title: e.target.value })}
                placeholder="Title"
              />
            </div>
            <Textarea
              value={item.description ?? ""}
              onChange={(e) => update(idx, { description: e.target.value })}
              placeholder="Description"
              rows={2}
            />
            <div>
              <Label className="text-xs text-muted-foreground">Deliverables (one per line)</Label>
              <Textarea
                value={item.deliverables.join("\n")}
                onChange={(e) =>
                  update(idx, { deliverables: e.target.value.split("\n").filter(Boolean) })
                }
                rows={3}
              />
            </div>
          </div>
          <Button variant="ghost" size="icon" onClick={() => remove(idx)} aria-label="Remove">
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ))}
      <Button variant="outline" size="sm" onClick={add}>
        <Plus className="mr-1 h-4 w-4" />
        Add scope item
      </Button>
    </div>
  );
}
