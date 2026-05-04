"use client";

import { useCallback, useRef, useState, type DragEvent } from "react";
import { Upload, FileText, Loader2, CheckCircle2, AlertCircle } from "lucide-react";

import type { Discipline, DocType, ProcessingStatus } from "./types";
import { DisciplineTag } from "./DisciplineTag";
import { cn } from "../lib/cn";

export interface UploadTask {
  id: string;
  file: File;
  discipline?: Discipline;
  doc_type?: DocType;
  status: "queued" | "uploading" | ProcessingStatus;
  progress?: number;
  error?: string;
}

interface DocumentUploadZoneProps {
  onFilesAdded(files: File[]): void;
  tasks?: UploadTask[];
  accept?: string;
  className?: string;
  disabled?: boolean;
}

export function DocumentUploadZone({
  onFilesAdded,
  tasks = [],
  accept = ".pdf,.docx,.dwg",
  className,
  disabled,
}: DocumentUploadZoneProps): JSX.Element {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);

  const handle = useCallback(
    (files: File[]) => {
      if (disabled) return;
      if (files.length > 0) onFilesAdded(files);
    },
    [disabled, onFilesAdded],
  );

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    handle(Array.from(e.dataTransfer.files));
  };

  return (
    <div className={cn("space-y-3", className)}>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={onDrop}
        onClick={() => !disabled && inputRef.current?.click()}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 text-center transition-colors",
          // Disabled state uses a muted border/bg instead of `opacity-60`
          // — opacity blends fg + bg and pushes the slate-500 / -700 copy
          // below WCAG AA contrast (axe reported 2.23 / 3.26 ratios).
          disabled
            ? "cursor-not-allowed border-slate-200 bg-slate-100"
            : isDragging
              ? "border-blue-500 bg-blue-50"
              : "border-slate-300 bg-slate-50 hover:border-slate-400 hover:bg-slate-100",
        )}
      >
        <Upload className={cn("mb-2", isDragging ? "text-blue-600" : "text-slate-400")} size={28} />
        <p className="text-sm font-medium text-slate-700">Kéo thả bản vẽ / tài liệu vào đây</p>
        <p className="mt-1 text-xs text-slate-500">hoặc bấm để chọn tệp — PDF, DOCX, DWG (tối đa 100MB)</p>
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          multiple
          className="hidden"
          onChange={(e) => {
            handle(Array.from(e.target.files ?? []));
            if (inputRef.current) inputRef.current.value = "";
          }}
        />
      </div>

      {tasks.length > 0 && (
        <ul className="space-y-2">
          {tasks.map((t) => (
            <UploadTaskRow key={t.id} task={t} />
          ))}
        </ul>
      )}
    </div>
  );
}

function UploadTaskRow({ task }: { task: UploadTask }): JSX.Element {
  const isDone = task.status === "ready";
  const isFailed = task.status === "failed";
  const isActive = task.status === "uploading" || task.status === "processing" || task.status === "pending";

  return (
    <li className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2">
      <FileText size={16} className="text-slate-500" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-slate-900">{task.file.name}</span>
          {task.discipline && <DisciplineTag discipline={task.discipline} size="sm" />}
        </div>
        <div className="mt-0.5 text-xs text-slate-500">
          {(task.file.size / (1024 * 1024)).toFixed(2)} MB
          {isActive && task.progress != null && ` · ${Math.round(task.progress * 100)}%`}
          {task.error && ` · ${task.error}`}
        </div>
      </div>
      {isActive && <Loader2 size={16} className="animate-spin text-blue-600" />}
      {isDone && <CheckCircle2 size={16} className="text-emerald-600" />}
      {isFailed && <AlertCircle size={16} className="text-red-600" />}
    </li>
  );
}
