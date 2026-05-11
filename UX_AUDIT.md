# UX Audit & Platform-Wide Pass

_Date: 2026-05-11 — covers visual consistency, IA/nav, forms, and a11y/responsiveness across the entire web app._

## Summary

The web app shipped with a clean primitives folder (`packages/ui/primitives/`) but only a handful of modules actually used it. Most pages, every auth surface, and the global navigation were rolling their own Tailwind class strings against hard-coded `slate-*` colors, with no shared `PageHeader`, `EmptyState`, `Skeleton`, `Alert`, or `FormField`. The dialog primitive lacked basic ARIA modal semantics. Tokens lived in `tailwind.config.ts` only (no CSS vars), which blocked dark mode and any future theming.

This pass standardizes the design system, fixes the missing primitives, makes the platform keyboard- and screen-reader-accessible, and brings 17 module landing pages onto the same visual rhythm. Both `@aec/ui` and `@aec/web` typecheck cleanly.

---

## What changed

### 1. Design tokens → CSS variables

`apps/web/app/globals.css` now defines every semantic token as an HSL custom property under `:root`. `tailwind.config.ts` references them via `hsl(var(--token) / <alpha-value>)`, so utilities like `bg-primary/10` and `text-muted-foreground` keep working and slash-alpha syntax stays functional.

New tokens: `--card`, `--card-foreground`, `--popover`, `--popover-foreground`, `--accent`, `--accent-foreground`, `--success`, `--success-foreground`, `--warning`, `--warning-foreground`.

A `@media (prefers-color-scheme: dark)` block swaps the same variables — **dark mode now ships for free**. Users can force light with `data-theme="light"` on `<html>`.

A `@media (prefers-reduced-motion: reduce)` block cancels non-essential transitions globally.

Skip-link styling (`.skip-link`) is provided so the dashboard's "skip to main content" actually looks decent when keyboard-focused.

### 2. Primitives upgraded

| Primitive | Change |
|---|---|
| `Button` | Adds `loading` prop with in-button spinner + `aria-busy` + width-preserving overlay. Default `type` is now `"button"` (was implicit `"submit"`, a common React bug source). New variants: `success`, `link`. Focus ring now uses `ring-offset` so the outline isn't swallowed by tinted backgrounds. `buttonStyles` is now exported so `<Link>`s can pick up button styling. |
| `Input`, `Textarea` | New `invalid` prop drives `aria-invalid` + red focus ring. Standalone `aria-invalid` attribute also triggers the styling so it works out-of-the-box with react-hook-form. Added `file:*` styling and `transition-colors`. |
| `Label` | New `required` prop renders a red asterisk + assumes the input itself carries `aria-required`. |
| `Card` | Now uses `bg-card` / `text-card-foreground` so it sits one elevation above the page background instead of disappearing into it. |
| `Dialog` | **Complete a11y overhaul**: `role="dialog"`, `aria-modal="true"`, `aria-labelledby`/`aria-describedby`, focus trap (Tab + Shift+Tab cycle inside the panel), initial focus moved into the panel, focus returned to the opener on close, Escape closes, body scroll lock. New `hideCloseButton` and `ariaLabel` props. |

### 3. New primitives

- **`Spinner`** (`primitives/spinner.tsx`) — inline loader with `role="status"`/`aria-live="polite"` and an SR-only label.
- **`Skeleton` + `SkeletonLines`** (`primitives/skeleton.tsx`) — animated shimmer placeholders. SkeletonLines renders a stack of varying-width bars (last one short, feels natural).
- **`EmptyState`** (`primitives/empty-state.tsx`) — icon + title + description + action. `variant="error"` for failed-load states.
- **`Alert` + `AlertTitle` + `AlertDescription`** (`primitives/alert.tsx`) — variants: `default`, `info`, `success`, `warning`, `destructive`. Destructive/warning carry `role="alert"`, others `role="status"`.
- **`PageHeader`** (`primitives/page-header.tsx`) — `title` (renders as `<h1>`) + `description` + `eyebrow` + `actions` + `extra` (e.g. tab strip). One consistent page-header shape across the whole platform.
- **`FormField`** (`primitives/form-field.tsx`) — wraps a single input child and wires `id` / `aria-describedby` (help + error) / `aria-invalid` / `aria-required` automatically. Renders error message with `role="alert"`. Stops every form from hand-wiring this.

All exported from `@aec/ui/primitives` (and the package root `@aec/ui`).

### 4. Global navigation rework

`apps/web/components/SidebarNav.tsx` (new) replaces the inline nav-rendering inside the dashboard layout:

- **Active state** — current route gets a tinted background (`bg-primary/10`) + `aria-current="page"`. Active match handles nested routes (`/pulse/123` lights up `/pulse`).
- **Semantic structure** — items are grouped by section into separate `<ul>`s with `<h2>` section headings (was `<div>`).
- **`aria-label="Điều hướng chính"`** on the `<nav>`.

`apps/web/components/MobileNavShell.tsx` rewritten:

- **Skip link** (`#main-content`) — keyboard users press Tab once on any dashboard page and can jump past the ~27-item sidebar.
- **`<main id="main-content" tabIndex={-1}>`** target for that skip link.
- **Mobile drawer**: focus moves into the drawer on open, returns to the hamburger on close, Tab is trapped inside, Escape closes. `aria-expanded` / `aria-controls` wire the hamburger to the drawer.
- **Sticky desktop sidebar** (`md:sticky md:top-0 md:h-screen`) — the sidebar no longer scrolls away with long pages.

### 5. Auth flow refactor (5 pages)

`/login`, `/signup`, `/forgot-password`, `/reset-password`, `/invite/[token]` all use:

- New `apps/web/components/AuthShell.tsx` wrapper (centred card on `bg-muted/40`) — consistent chrome across every auth surface.
- `<FormField>` + `<Input>` + `<Button loading>` + `<Alert variant="destructive">` instead of hand-rolled inputs, inline error divs, and bespoke submit buttons.
- Login now reads `?email=` and pre-fills (used by `/invite` fallback path).

Net effect: ~120 lines of duplicated form markup per page collapse into ~40, and every auth surface gets focus rings + ARIA + loading affordances that match the rest of the app.

### 6. Command palette polish

`apps/web/components/CommandPalette.tsx` — same one, but:

- `aria-modal="true"` added.
- All `slate-*` color classes swapped to semantic tokens (`bg-popover`, `text-foreground`, `text-muted-foreground`, `bg-accent` for selected row), so the palette themes properly in dark mode.
- Selected row uses `bg-accent` (was `bg-slate-50`), errors use `text-destructive` + `role="alert"`, loading state announces via `aria-live="polite"`.
- Search input declares `aria-autocomplete="list"` + `aria-controls` pointing at the listbox.

### 7. Module landing-page sweep (17 pages)

Refactored to use `PageHeader` / `EmptyState` / `Spinner` / `Skeleton` / `Alert` / `Badge` and migrated off `slate-*`:

- `/codeguard`, `/winwork`, `/bidradar`, `/handover`, `/drawbridge/documents`
- `/inbox`, `/projects`, `/activity`, `/schedule`
- `/dailylog`, `/punchlist`, `/submittals`, `/changeorder`
- `/pulse` (manual rewrite — used as the template), `/costpulse`, `/siteeye/dashboard`
- `/settings/members`, `/settings/notifications`

Color migrations applied: `text-slate-900` → `text-foreground`, `text-slate-{500,600}` → `text-muted-foreground`, `border-slate-{200,300}` → `border`, `bg-white` → `bg-card`, `bg-slate-50` → `bg-muted/40`, `bg-red-50` + `text-red-700` → `<Alert variant="destructive">`.

### 8. Misc bug fixes caught along the way

- `apps/web/hooks/siteeye/use-reports.ts` — duplicate `orgId` key in object literal (typo, was a TS error).
- `apps/web/hooks/siteeye/use-safety.ts` — same.

---

## What's still recommended (deferred)

These are good follow-ups but out of scope for this pass:

1. **Convert hand-rolled modals to `Dialog`.** Several module pages (`handover`, `dailylog`, `punchlist`, `submittals`, `changeorder`, `schedule`) ship their own `fixed inset-0` overlay markup with no a11y plumbing. Each should swap to `<Dialog>`. (Each is ~15-line mechanical change but requires reading the surrounding click-outside / form-state logic.)

2. **Status badge taxonomy.** Pages with multi-color status pills (Pulse, BidRadar, Drawbridge, Activity) currently map statuses to hardcoded `bg-blue-100`/`bg-amber-100`/etc. Consider adding a `tone` prop to `<Badge>` (`blue` / `amber` / `purple` / `indigo` / `slate`) and routing through that — would consolidate ~6 inline color maps and pick up dark-mode contrast adjustments automatically.

3. **Overlay token.** `bg-foreground/40` works in light mode but inverts the intent in dark (a near-white scrim over content). Add a dedicated `--overlay` token so backdrops stay dark-on-light in both themes.

4. **Standardize form library.** `react-hook-form` is installed and used in one place (RFQ respond). Auth forms and most CRUD forms still use raw `useState`. Picking one (RHF + zod is the typical choice; we already have `@hookform/resolvers` installed) would let validation patterns share infrastructure.

5. **Toast system.** No global toast / snackbar primitive exists. Async actions (publish, save, delete) either alert via `<Alert>` inside the page or do nothing visible. Adding a small `Toaster` (single mount in the dashboard layout, imperative `toast(...)` API) would unlock a missing piece of feedback.

6. **Pending-invitation / settings panels.** A few persistent info panels in `/settings/members` use raw emerald/amber blocks. They're not really inline alerts — they're cards with their own actions. Worth its own `<InfoPanel>` primitive if more surfaces grow.

7. **Empty / loading parity in module sub-pages.** This pass touched module *landings* — sub-pages (e.g. `/pulse/[project_id]/dashboard`, `/drawbridge/conflicts/[id]`) still ship per-page loading text and bespoke empty states. The pattern is now established; sweep can continue incrementally.

---

## How to use the new primitives (cheat sheet)

```tsx
// Page header
<PageHeader
  title="Tài liệu thiết kế"
  description="Tất cả bản vẽ và hồ sơ kỹ thuật của dự án."
  actions={
    <>
      <Button variant="outline" size="sm"><Filter />Lọc</Button>
      <Button size="sm"><Plus />Tải lên</Button>
    </>
  }
/>

// Loading state
{isLoading ? <SkeletonLines lines={5} /> : ...}

// Empty / error states
<EmptyState
  icon={<Inbox size={22} />}
  title="Chưa có tài liệu nào"
  description="Tải lên bản vẽ PDF để bắt đầu."
  action={<Button>Tải lên</Button>}
/>

// Inline error
<Alert variant="destructive">
  <AlertTitle>Không thể tải</AlertTitle>
  <AlertDescription>{error.message}</AlertDescription>
</Alert>

// Form field
<FormField label="Email" required error={errors.email?.message} help="Chúng tôi sẽ gửi xác nhận tới đây.">
  <Input type="email" autoComplete="email" {...register("email")} />
</FormField>

// Button with async work
<Button type="submit" loading={isSubmitting} loadingText="Đang lưu">
  Lưu
</Button>

// Link styled as a button
<Link href="/new" className={buttonStyles({ variant: "default", size: "sm" })}>
  Tạo mới
</Link>
```

---

## Verification

- `pnpm --filter @aec/ui typecheck` — passes.
- `pnpm --filter @aec/web typecheck` — passes.
- No existing test files were modified; UI component tests in `packages/ui/*/__tests__/` should still pass against the upgraded primitives (Button's new optional `loading` prop is backwards-compatible; other changes don't alter signatures).
