"use client";

import { ExternalLink } from "lucide-react";
import type { Citation } from "./types";

interface CitationCardProps {
  citation: Citation;
  index?: number;
}

export function CitationCard({ citation, index }: CitationCardProps): JSX.Element {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
      <div className="mb-1 flex items-center justify-between">
        <div className="font-medium text-slate-900">
          {index !== undefined && <span className="mr-2 text-slate-500">[{index + 1}]</span>}
          {citation.regulation}
          <span className="ml-2 text-slate-600">§ {citation.section}</span>
        </div>
        {citation.source_url && (
          <a
            href={citation.source_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
          >
            Nguồn <ExternalLink size={12} />
          </a>
        )}
      </div>
      <blockquote className="border-l-2 border-blue-400 pl-3 italic text-slate-700">
        {citation.excerpt}
      </blockquote>
    </div>
  );
}
