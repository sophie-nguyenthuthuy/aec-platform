// Module augmentation that wires `vitest-axe`'s `toHaveNoViolations`
// into Vitest 2.x's `Assertion` interface.
//
// Why this exists
// ---------------
// `vitest-axe@0.1.x` ships an ambient declaration that augments the
// legacy `Vi.Assertion` namespace. Vitest 2.x moved the matcher
// interface to `Assertion<T>` exported from `@vitest/expect`, so the
// upstream augmentation no longer reaches the spot tsc actually
// resolves when typing `expect(...).toHaveNoViolations()`. This file
// closes that gap with a one-shot module-augmentation pointing at the
// new location. Drop it when vitest-axe ships native v2 typings.

import "vitest";
import type { AxeMatchers } from "vitest-axe/matchers";

declare module "vitest" {
  interface Assertion<T = any> extends AxeMatchers {}
  interface AsymmetricMatchersContaining extends AxeMatchers {}
}
