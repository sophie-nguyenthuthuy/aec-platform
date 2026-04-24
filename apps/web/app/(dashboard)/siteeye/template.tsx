"use client";
import type { ReactNode } from "react";

import { ProjectProvider } from "./project-context";

export default function SiteEyeTemplate({ children }: { children: ReactNode }) {
  return <ProjectProvider>{children}</ProjectProvider>;
}
