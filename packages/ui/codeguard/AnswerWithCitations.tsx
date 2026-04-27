"use client";

import type { ReactNode } from "react";
import type { Citation } from "./types";

interface AnswerWithCitationsProps {
  /** Answer text. May contain `[N]` markers (1-indexed) referring to
   *  the `citations` array — those markers get rewritten as inline
   *  hover-expanded `<CitationMarker>` components. Plain text without
   *  markers passes through unchanged. */
  text: string;
  /** Citations indexed parallel to the prompt's instructed convention:
   *  `[1]` → citations[0], `[2]` → citations[1], etc. */
  citations: Citation[];
  /** Optional className applied to the wrapper `<p>`. Lets pages
   *  preserve their existing typography (e.g. `whitespace-pre-wrap`)
   *  without re-implementing it here. */
  className?: string;
}

/**
 * Render an answer with inline `[N]` citation markers expanded.
 *
 * The LLM emits `[N]` (1-indexed) immediately after each factual claim
 * — see the `_QA_SYSTEM` prompt in `apps/ml/pipelines/codeguard.py`.
 * This component splits the text on those markers and substitutes
 * `<CitationMarker>` chips that hover-expand to show the cited
 * section + excerpt.
 *
 * Defensive against the LLM mis-numbering: a marker that points past
 * the end of `citations` is rendered as plain text (the literal
 * `[N]`). That's better than dropping it silently or rendering an
 * empty popover.
 */
export function AnswerWithCitations({
  text,
  citations,
  className,
}: AnswerWithCitationsProps): JSX.Element {
  const parts = parseMarkers(text, citations);
  return <p className={className}>{parts}</p>;
}

/**
 * Inline citation chip that hover-expands to show the cited section +
 * excerpt. Pure CSS (Tailwind `group-hover` + `group-focus-within`)
 * — no JS state, no portal — so it composes cleanly inside streamed
 * text without re-renders.
 *
 * Why both `hover` and `focus-within`: `hover` covers mouse, but
 * keyboard-only users need the popover to appear when they tab to the
 * `<button>`. Both selectors are cheap.
 */
export function CitationMarker({
  citation,
  index,
}: {
  citation: Citation;
  index: number; // 0-indexed in `citations`; displayed as index+1
}): JSX.Element {
  return (
    <span className="group relative inline-block align-baseline">
      <button
        type="button"
        aria-label={`Trích dẫn ${index + 1}: ${citation.regulation} § ${citation.section}`}
        className="mx-0.5 inline-flex items-baseline rounded bg-blue-100 px-1.5 py-0.5 text-xs font-medium text-blue-700 hover:bg-blue-200 focus:outline-none focus:ring-2 focus:ring-blue-400"
      >
        [{index + 1}]
      </button>
      <span
        role="tooltip"
        className="invisible absolute bottom-full left-0 z-10 mb-1 w-72 rounded-md bg-slate-900 p-2 text-xs text-white opacity-0 shadow-lg transition group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100"
      >
        <span className="block font-medium">
          {citation.regulation}
          <span className="ml-2 opacity-70">§ {citation.section}</span>
        </span>
        <span className="mt-1 block italic text-slate-200">{citation.excerpt}</span>
      </span>
    </span>
  );
}

const MARKER_RE = /\[(\d+)\]/g;

/** Split `text` into alternating string + `<CitationMarker>` parts. */
function parseMarkers(text: string, citations: Citation[]): ReactNode[] {
  const parts: ReactNode[] = [];
  let lastEnd = 0;
  for (const match of text.matchAll(MARKER_RE)) {
    const start = match.index ?? 0;
    if (start > lastEnd) parts.push(text.slice(lastEnd, start));
    const num = Number(match[1]);
    const cite = citations[num - 1];
    if (cite) {
      parts.push(
        <CitationMarker key={`m-${start}`} citation={cite} index={num - 1} />,
      );
    } else {
      // Out-of-range marker — defend by rendering literal text rather
      // than dropping or rendering an empty popover.
      parts.push(match[0]);
    }
    lastEnd = start + match[0].length;
  }
  if (lastEnd < text.length) parts.push(text.slice(lastEnd));
  return parts;
}
