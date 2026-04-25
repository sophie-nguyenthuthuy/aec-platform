"use client";

import { useEffect, useRef, useState } from "react";

import type { BBox } from "./types";
import { cn } from "../lib/cn";

export interface PdfHighlight {
  id: string;
  page: number;
  bbox: BBox;
  label?: string;
  tone?: "info" | "warning" | "danger";
}

interface PDFViewerProps {
  /** URL or Blob-URL for the PDF file. */
  src: string;
  page?: number;
  highlights?: PdfHighlight[];
  onHighlightClick?(highlight: PdfHighlight): void;
  className?: string;
  /** Dynamically import pdfjs-dist from this path. Default: "pdfjs-dist". */
  pdfjsPath?: string;
}

const TONE_COLORS: Record<NonNullable<PdfHighlight["tone"]>, string> = {
  info: "border-blue-500 bg-blue-400/25",
  warning: "border-amber-500 bg-amber-400/25",
  danger: "border-red-500 bg-red-400/25",
};

/**
 * Minimal PDF.js wrapper. Renders a single page to canvas and overlays highlight boxes.
 * Consumers are expected to load `pdfjs-dist` as a peer dep in the host app.
 */
export function PDFViewer({
  src,
  page = 1,
  highlights = [],
  onHighlightClick,
  className,
  pdfjsPath = "pdfjs-dist",
}: PDFViewerProps): JSX.Element {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [dims, setDims] = useState<{ width: number; height: number }>({ width: 800, height: 1100 });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // pdfjs RenderTask exposes both `promise` and `cancel()`. We don't
    // import the type to keep pdfjs an optional peer dep.
    let renderTask: { cancel(): void; promise: Promise<unknown> } | null = null;

    (async () => {
      try {
        const pdfjs: any = await import(/* webpackIgnore: true */ pdfjsPath);
        pdfjs.GlobalWorkerOptions.workerSrc =
          pdfjs.GlobalWorkerOptions.workerSrc ||
          `https://cdn.jsdelivr.net/npm/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

        const doc = await pdfjs.getDocument(src).promise;
        if (cancelled) return;
        const pdfPage = await doc.getPage(page);
        if (cancelled) return;

        const viewport = pdfPage.getViewport({ scale: 1.3 });
        const canvas = canvasRef.current;
        if (!canvas) return;
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        setDims({ width: viewport.width, height: viewport.height });
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        renderTask = pdfPage.render({ canvasContext: ctx, viewport });
        await renderTask?.promise;
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load PDF");
        }
      }
    })();

    return () => {
      cancelled = true;
      renderTask?.cancel?.();
    };
  }, [src, page, pdfjsPath]);

  const pageHighlights = highlights.filter((h) => h.page === page);

  return (
    <div className={cn("relative inline-block rounded-lg border border-slate-200 bg-white shadow-sm", className)}>
      {error ? (
        <div className="p-6 text-sm text-red-600">{error}</div>
      ) : (
        <>
          <canvas ref={canvasRef} className="block max-w-full" />
          <div className="pointer-events-none absolute inset-0" style={{ width: dims.width, height: dims.height }}>
            {pageHighlights.map((h) => (
              <button
                key={h.id}
                type="button"
                onClick={() => onHighlightClick?.(h)}
                style={{
                  position: "absolute",
                  left: h.bbox.x,
                  top: h.bbox.y,
                  width: h.bbox.width,
                  height: h.bbox.height,
                }}
                className={cn(
                  "pointer-events-auto rounded border-2 transition-opacity hover:opacity-80",
                  TONE_COLORS[h.tone ?? "info"],
                )}
                aria-label={h.label ?? "Highlight"}
                title={h.label}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
