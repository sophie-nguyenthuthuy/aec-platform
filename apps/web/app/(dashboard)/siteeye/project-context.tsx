"use client";
import { createContext, useContext, useState, type ReactNode } from "react";

interface ProjectCtx {
  projectId: string | null;
  setProjectId: (id: string | null) => void;
}

const Ctx = createContext<ProjectCtx | null>(null);

export function ProjectProvider({ children }: { children: ReactNode }) {
  const [projectId, setProjectId] = useState<string | null>(
    typeof window === "undefined"
      ? null
      : window.localStorage.getItem("siteeye.project_id"),
  );

  function update(next: string | null) {
    setProjectId(next);
    if (typeof window !== "undefined") {
      if (next) window.localStorage.setItem("siteeye.project_id", next);
      else window.localStorage.removeItem("siteeye.project_id");
    }
  }

  return <Ctx.Provider value={{ projectId, setProjectId: update }}>{children}</Ctx.Provider>;
}

export function useSelectedProject(): ProjectCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSelectedProject must be used inside <ProjectProvider>");
  return ctx;
}
