"use client";

import { useEffect, useState } from "react";
import type { MaterialPrice } from "@aec/types";

import { cn } from "../lib/cn";
import { Input } from "../primitives/input";
import { formatVnd } from "./formatters";

interface MaterialSearchProps {
  onSearch: (query: string) => Promise<MaterialPrice[]>;
  onSelect?: (price: MaterialPrice) => void;
  placeholder?: string;
  className?: string;
}

export function MaterialSearch({
  onSearch,
  onSelect,
  placeholder = "Search materials…",
  className,
}: MaterialSearchProps): JSX.Element {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<MaterialPrice[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (query.trim().length < 2) {
      setResults([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const items = await onSearch(query.trim());
        if (!cancelled) {
          setResults(items);
          setOpen(true);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, onSearch]);

  return (
    <div className={cn("relative", className)}>
      <Input
        value={query}
        placeholder={placeholder}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => results.length > 0 && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {open && (results.length > 0 || loading) && (
        <div className="absolute z-10 mt-1 max-h-80 w-full overflow-auto rounded-md border border-slate-200 bg-white shadow-lg">
          {loading && <div className="px-3 py-2 text-xs text-slate-500">Loading…</div>}
          {results.map((r) => (
            <button
              key={r.id}
              type="button"
              onClick={() => {
                onSelect?.(r);
                setQuery(r.name);
                setOpen(false);
              }}
              className="flex w-full items-center justify-between gap-3 border-b border-slate-100 px-3 py-2 text-left text-sm hover:bg-slate-50"
            >
              <div className="min-w-0">
                <div className="truncate font-medium text-slate-900">{r.name}</div>
                <div className="text-xs text-slate-500">
                  {r.material_code} · {r.province ?? "National"} · {r.unit}
                </div>
              </div>
              <div className="whitespace-nowrap text-sm font-semibold text-emerald-700">
                {formatVnd(r.price_vnd)}/{r.unit}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
