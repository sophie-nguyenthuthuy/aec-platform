"use client";

/**
 * Cmd+K palette affordance.
 *
 * Lives in its own client-component file so the parent dashboard layout
 * can stay server-rendered. Inlining a button with an `onClick` directly
 * inside the server-component layout throws "Event handlers cannot be
 * passed to Client Component props" at runtime — Next.js 14 errors out
 * before the page renders, breaking every authenticated route. This was
 * the actual cause of the post-login redirect-loop the real-auth
 * Playwright suite saw.
 *
 * The button doesn't open the palette directly: it dispatches a
 * synthetic keyboard event so the global listener in `<CommandPalette>`
 * handles the toggle, keeping open-state in one place.
 */

export function SearchTrigger() {
  return (
    <button
      type="button"
      onClick={() =>
        window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true }))
      }
      className="mb-4 flex items-center justify-between rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-500 hover:bg-slate-50"
    >
      <span className="flex items-center gap-2">
        <SearchIcon />
        Tìm kiếm...
      </span>
      <kbd className="rounded border border-slate-300 bg-slate-50 px-1.5 py-0.5 font-mono text-[10px]">
        ⌘K
      </kbd>
    </button>
  );
}


function SearchIcon() {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  );
}
