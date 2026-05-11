"use client";

import {
  type ChangeEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  BookOpen,
  FileText,
  HelpCircle,
  Search,
  ShieldCheck,
  Wrench,
  X,
} from "lucide-react";

import {
  type MatchedOn,
  type SearchResult,
  type SearchScope,
  useSearch,
} from "@/hooks/search";


// Per-scope visual treatment + Vietnamese label. Co-located here (not in
// types) because it's purely a presentation concern — the API returns
// the bare scope slug.
const SCOPE_META: Record<
  SearchScope,
  { label: string; tone: string; icon: React.ReactNode }
> = {
  documents: {
    label: "Tài liệu",
    tone: "bg-blue-100 text-blue-800",
    icon: <FileText size={12} />,
  },
  regulations: {
    label: "Quy chuẩn",
    tone: "bg-rose-100 text-rose-800",
    icon: <ShieldCheck size={12} />,
  },
  defects: {
    label: "Lỗi",
    tone: "bg-amber-100 text-amber-800",
    icon: <Wrench size={12} />,
  },
  rfis: {
    label: "RFI",
    tone: "bg-indigo-100 text-indigo-800",
    icon: <HelpCircle size={12} />,
  },
  proposals: {
    label: "Đề xuất",
    tone: "bg-emerald-100 text-emerald-800",
    icon: <BookOpen size={12} />,
  },
};


/**
 * Cross-module command palette. Cmd+K (or Ctrl+K on Linux/Win) opens it,
 * Esc closes, ↑/↓ navigate, Enter follows the selected result's route.
 *
 * Search is debounced at 200ms — fast enough that users don't feel
 * latency, slow enough that we don't fan out 5 SQL queries per
 * keystroke against a real cluster.
 */
export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const search = useSearch();

  // ---------- Open / close lifecycle ----------

  // Cmd+K / Ctrl+K toggles. We listen at window level so the shortcut
  // works from anywhere, including inside textareas / form fields.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const isToggle = (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k";
      if (isToggle) {
        e.preventDefault();
        setOpen((o) => !o);
        return;
      }
      if (e.key === "Escape" && open) {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // Reset state when the modal opens. Otherwise stale results from a
  // previous session linger behind a fresh empty input.
  useEffect(() => {
    if (open) {
      setQuery("");
      setSelectedIdx(0);
      search.reset();
      // Focus on next tick so the input exists in the DOM first.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open, search]);

  // ---------- Debounced search ----------

  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      // Backend rejects <2 chars; mirror that here so we don't fire a
      // doomed network call on every single character.
      search.reset();
      return;
    }
    const handle = setTimeout(() => {
      search.mutate({ query: trimmed, limit: 20 });
    }, 200);
    return () => clearTimeout(handle);
    // We deliberately exclude `search` from deps — it's a stable
    // mutation handle and including it loops on every result update.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  // Memoised so the `?? []` fallback returns a stable reference across
  // renders. Without this, every render produces a fresh `[]`, which makes
  // any downstream `useCallback`/`useMemo` keyed on `results` re-run every
  // tick (caught by react-hooks/exhaustive-deps).
  const results: SearchResult[] = useMemo(
    () => search.data?.results ?? [],
    [search.data?.results],
  );

  // Reset the selection when the result list changes shape. Otherwise
  // ↑/↓ off the end of an old longer list lands on a stale index.
  useEffect(() => {
    setSelectedIdx(0);
  }, [results.length]);

  // ---------- Keyboard navigation inside the modal ----------

  const onInputKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (results.length === 0) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIdx((i) => Math.min(i + 1, results.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIdx((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        const target = results[selectedIdx];
        if (target?.route) {
          setOpen(false);
          router.push(target.route);
        }
      }
    },
    [results, selectedIdx, router],
  );

  const onResultClick = useCallback(
    (result: SearchResult) => {
      if (!result.route) return;
      setOpen(false);
      router.push(result.route);
    },
    [router],
  );

  // ---------- Header strip: result count by scope ----------
  const countsByScope = useMemo(() => {
    const map = new Map<SearchScope, number>();
    for (const r of results) {
      map.set(r.scope, (map.get(r.scope) ?? 0) + 1);
    }
    return map;
  }, [results]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-foreground/40 backdrop-blur-[1px] animate-fade-in px-4 pt-24"
      onClick={() => setOpen(false)}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-2xl overflow-hidden rounded-xl border bg-popover text-popover-foreground shadow-2xl animate-zoom-in"
      >
        {/* ---------- Search input ---------- */}
        <div className="flex items-center gap-2 border-b px-4 py-3">
          <Search size={16} className="shrink-0 text-muted-foreground" aria-hidden="true" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e: ChangeEvent<HTMLInputElement>) =>
              setQuery(e.target.value)
            }
            onKeyDown={onInputKeyDown}
            placeholder="Tìm tài liệu, quy chuẩn, RFI, lỗi, đề xuất..."
            className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
            aria-label="Search query"
            aria-autocomplete="list"
            aria-controls="cmdk-listbox"
          />
          <button
            type="button"
            onClick={() => setOpen(false)}
            aria-label="Đóng"
            className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            <X size={14} aria-hidden="true" />
          </button>
        </div>

        {/* ---------- Results / state ---------- */}
        <div className="max-h-[60vh] overflow-y-auto">
          {query.trim().length < 2 ? (
            <EmptyHint />
          ) : search.isPending ? (
            <p
              role="status"
              aria-live="polite"
              className="px-4 py-8 text-center text-sm text-muted-foreground"
            >
              Đang tìm...
            </p>
          ) : search.isError ? (
            <div role="alert" className="flex items-start gap-2 px-4 py-6 text-sm text-destructive">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
              <p>
                Lỗi tìm kiếm:{" "}
                {(search.error as Error)?.message ?? "thử lại sau."}
              </p>
            </div>
          ) : results.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-muted-foreground">
              Không có kết quả cho{" "}
              <span className="font-medium text-foreground">"{query}"</span>.
            </p>
          ) : (
            <>
              {/* Result-count strip — small but useful: tells the user
                  WHERE matches landed without making them eyeball the
                  scope chip on every row. */}
              <div className="flex flex-wrap gap-1.5 border-b px-4 py-2 text-[11px]">
                {Array.from(countsByScope.entries()).map(([scope, n]) => (
                  <span
                    key={scope}
                    className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 ${SCOPE_META[scope].tone}`}
                  >
                    {SCOPE_META[scope].icon}
                    {SCOPE_META[scope].label} · {n}
                  </span>
                ))}
              </div>
              <ul id="cmdk-listbox" role="listbox">
                {results.map((r, i) => (
                  <li key={`${r.scope}-${r.id}`}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={i === selectedIdx}
                      onClick={() => onResultClick(r)}
                      onMouseEnter={() => setSelectedIdx(i)}
                      className={`flex w-full items-start gap-3 px-4 py-2.5 text-left focus-visible:outline-none ${
                        i === selectedIdx ? "bg-accent" : "bg-popover"
                      }`}
                    >
                      <span
                        className={`mt-0.5 inline-flex h-5 items-center gap-1 rounded-full px-1.5 text-[10px] font-medium ${SCOPE_META[r.scope].tone}`}
                      >
                        {SCOPE_META[r.scope].icon}
                        {SCOPE_META[r.scope].label}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-baseline gap-2">
                          <p className="truncate text-sm font-medium text-foreground">
                            {r.title}
                          </p>
                          <MatchChip matchedOn={r.matched_on} />
                        </div>
                        {r.snippet && (
                          <p className="mt-0.5 truncate text-xs text-muted-foreground">
                            {r.snippet}
                          </p>
                        )}
                        {r.project_name && (
                          <p className="mt-0.5 text-[11px] text-muted-foreground/80">
                            {r.project_name}
                          </p>
                        )}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>

        {/* ---------- Footer: keyboard hints ---------- */}
        <div className="flex items-center justify-between border-t bg-muted/40 px-4 py-2 text-[11px] text-muted-foreground">
          <span>
            <Kbd>↑</Kbd> <Kbd>↓</Kbd> điều hướng · <Kbd>↵</Kbd> mở ·{" "}
            <Kbd>esc</Kbd> đóng
          </span>
          {results.length > 0 && (
            <span>
              {results.length} kết quả
            </span>
          )}
        </div>
      </div>
    </div>
  );
}


/**
 * Provenance chip for a search result. Tells the user *why* this row
 * landed in the list — exact text match, semantic match, or both.
 *
 * `null` (keyword-only scopes that have no embeddings table, or when
 * the server skipped the vector arm because no OPENAI_API_KEY was set)
 * renders nothing — the chip would be a noisy "keyword" everywhere
 * and we'd lose the signal value of the chip when both arms ran.
 */
function MatchChip({ matchedOn }: { matchedOn: MatchedOn | null }) {
  if (matchedOn === null) return null;
  const meta: Record<MatchedOn, { label: string; tone: string }> = {
    keyword: { label: "exact text", tone: "bg-slate-100 text-slate-600" },
    vector: { label: "semantic", tone: "bg-violet-100 text-violet-700" },
    both: { label: "exact + semantic", tone: "bg-emerald-100 text-emerald-700" },
  };
  const { label, tone } = meta[matchedOn];
  return (
    <span
      className={`shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-medium ${tone}`}
      title={`Matched via ${matchedOn}`}
    >
      {label}
    </span>
  );
}


function EmptyHint() {
  return (
    <div className="px-4 py-8 text-center text-xs text-muted-foreground">
      <p>
        Gõ ít nhất 2 ký tự để tìm trên tất cả module:
      </p>
      <div className="mt-3 flex flex-wrap justify-center gap-1.5">
        {(Object.keys(SCOPE_META) as SearchScope[]).map((scope) => (
          <span
            key={scope}
            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 ${SCOPE_META[scope].tone}`}
          >
            {SCOPE_META[scope].icon}
            {SCOPE_META[scope].label}
          </span>
        ))}
      </div>
    </div>
  );
}


function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded border bg-card px-1 py-0.5 font-mono text-[10px] text-foreground">
      {children}
    </kbd>
  );
}
