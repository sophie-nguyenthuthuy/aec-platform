"use client";

import { useProjects } from "@/hooks/projects";

interface ProjectSelectProps {
  value: string;
  onChange: (id: string) => void;
  className?: string;
}

export function ProjectSelect({ value, onChange, className }: ProjectSelectProps) {
  const { data, isLoading } = useProjects({ per_page: 100 });
  const projects = data?.data ?? [];

  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={
        className ??
        "w-64 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
      }
    >
      <option value="">{isLoading ? "Đang tải..." : "Tất cả dự án"}</option>
      {projects.map((p) => (
        <option key={p.id} value={p.id}>
          {p.name}
        </option>
      ))}
    </select>
  );
}
