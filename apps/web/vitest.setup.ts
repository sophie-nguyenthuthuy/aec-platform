// Extend Vitest's `expect` with Testing Library's DOM matchers
// (`toBeInTheDocument`, `toHaveClass`, etc.). Without this, every
// matcher in component tests has to be hand-rolled.
//
// The `apps/web` vitest scope was originally hooks + lib helpers
// only (per `vitest.config.ts`'s commentary). Sparkline /
// TesterResults are the first isolated *component* tests added —
// they're pure React with no Next.js router / RSC dependencies, so
// they fit the spirit of the existing scope. If we ever land tests
// that need a router, those go through the Playwright lane.
import "@testing-library/jest-dom/vitest";
