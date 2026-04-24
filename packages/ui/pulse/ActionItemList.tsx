"use client";
import { Plus } from "lucide-react";
import type { ActionItem } from "@aec/types/pulse";
import { Button } from "../primitives/button";

export interface ActionItemListProps {
  items: ActionItem[];
  onCreateTask?: (title: string, deadline: string | null) => void;
}

export function ActionItemList({ items, onCreateTask }: ActionItemListProps) {
  if (items.length === 0) {
    return <p className="text-xs text-muted-foreground">No action items.</p>;
  }

  return (
    <ul className="space-y-2">
      {items.map((item, idx) => (
        <li
          key={`${item.title}-${idx}`}
          className="flex items-start justify-between gap-2 rounded-md border bg-background p-2"
        >
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{item.title}</p>
            <p className="text-xs text-muted-foreground">
              {item.owner ?? "Unassigned"}
              {item.deadline && ` • ${new Date(item.deadline).toLocaleDateString()}`}
            </p>
          </div>
          {onCreateTask && (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => onCreateTask(item.title, item.deadline)}
            >
              <Plus className="mr-1 h-3 w-3" />
              Create task
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}
