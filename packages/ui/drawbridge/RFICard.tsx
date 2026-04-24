"use client";

import { Calendar, Flag, MessageSquare, User } from "lucide-react";

import type { Rfi, RfiPriority, RfiStatus } from "./types";
import { cn } from "../lib/cn";

interface RFICardProps {
  rfi: Rfi;
  onOpen?(rfi: Rfi): void;
  onAnswer?(rfi: Rfi): void;
  className?: string;
}

const STATUS_STYLE: Record<RfiStatus, string> = {
  open: "bg-blue-100 text-blue-800",
  answered: "bg-amber-100 text-amber-800",
  closed: "bg-slate-100 text-slate-600",
};

const PRIORITY_STYLE: Record<RfiPriority, string> = {
  low: "text-slate-500",
  normal: "text-slate-600",
  high: "text-amber-600",
  urgent: "text-red-600",
};

export function RFICard({ rfi, onOpen, onAnswer, className }: RFICardProps): JSX.Element {
  const overdue = rfi.due_date && rfi.status !== "closed" && new Date(rfi.due_date) < new Date();

  return (
    <article
      onClick={() => onOpen?.(rfi)}
      className={cn(
        "group cursor-pointer rounded-lg border border-slate-200 bg-white p-3 shadow-sm transition-shadow hover:shadow",
        className,
      )}
    >
      <div className="mb-1 flex items-center gap-2 text-xs">
        {rfi.number && <span className="font-mono font-semibold text-slate-700">{rfi.number}</span>}
        <span className={cn("rounded-full px-2 py-0.5 font-medium", STATUS_STYLE[rfi.status])}>
          {rfi.status}
        </span>
        <Flag size={12} className={PRIORITY_STYLE[rfi.priority]} />
        <span className={cn("font-medium", PRIORITY_STYLE[rfi.priority])}>{rfi.priority}</span>
      </div>

      <h3 className="line-clamp-2 text-sm font-semibold text-slate-900">{rfi.subject}</h3>
      {rfi.description && (
        <p className="mt-1 line-clamp-2 text-xs text-slate-600">{rfi.description}</p>
      )}

      <footer className="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-500">
        {rfi.assigned_to && (
          <span className="inline-flex items-center gap-1">
            <User size={12} />
            {rfi.assigned_to.slice(0, 8)}
          </span>
        )}
        {rfi.due_date && (
          <span className={cn("inline-flex items-center gap-1", overdue && "font-semibold text-red-600")}>
            <Calendar size={12} />
            {new Date(rfi.due_date).toLocaleDateString()}
            {overdue && " (trễ hạn)"}
          </span>
        )}
        {rfi.related_document_ids.length > 0 && (
          <span className="inline-flex items-center gap-1">
            <MessageSquare size={12} />
            {rfi.related_document_ids.length} tài liệu
          </span>
        )}
        {onAnswer && rfi.status === "open" && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onAnswer(rfi);
            }}
            className="ml-auto rounded-md bg-blue-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-blue-700"
          >
            Trả lời
          </button>
        )}
      </footer>
    </article>
  );
}
