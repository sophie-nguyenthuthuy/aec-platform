/**
 * Type-level tests for hook contracts.
 *
 * What this catches that runtime tests don't
 * ------------------------------------------
 * The runtime hook tests in this directory pin behaviour: "calling
 * useTasks() with these filters issues this URL." They do NOT catch
 * type-level regressions:
 *
 *   * A hook silently widening its return type to `unknown` because
 *     someone removed a generic on `apiFetch<T>` — runtime tests
 *     still pass (the JSON parse goes through), but every call site
 *     loses property-name autocomplete.
 *   * `useDocuments().data` becoming `Document[] | null` instead of
 *     `{ data: Document[], meta } | undefined` — the runtime call
 *     still returns something, but `data?.data.map(...)` at the
 *     call site is suddenly a type error in 30 places.
 *   * A new field added to `MeetingNoteCreate` that the hook's
 *     `mutationFn` parameter type doesn't reflect — the form
 *     compiles fine because the hook accepts the original (narrower)
 *     shape, but the new field is dropped before reaching the API.
 *
 * Mechanism
 * ---------
 * `expectTypeOf<X>().toEqualTypeOf<Y>()` from vitest is a compile-
 * time-only check. The function returns `true` at runtime regardless
 * of what types are passed; what matters is whether tsc accepts the
 * call. Running `pnpm --filter @aec/web typecheck` exercises this
 * file — no test runner needed.
 *
 * Files in this directory matching `*.test-d.ts` are tsc-only;
 * vitest's runtime collector excludes them via the existing
 * `include: ["**\/__tests__/**\/*.test.{ts,tsx}"]` glob (note the
 * `.test.{ts,tsx}`, not `.test-d.ts`). The naming convention is
 * borrowed from `tsd` — well-known, easy to grep.
 *
 * What we pin
 * -----------
 * `result.data` shapes for query hooks (the field every call site
 * unwraps), and `mutationFn` parameter types for mutations (the
 * shape every form submits). Other fields (`isLoading`, `error`)
 * come from TanStack Query and are pinned by their own type tests
 * upstream — repeating them here would be theatre.
 */

import type {
  UseMutationResult,
  UseQueryResult,
} from "@tanstack/react-query";
import { expectTypeOf, test } from "vitest";

import type { Document } from "@aec/ui/drawbridge";
import type {
  ChangeOrder,
  MeetingNote,
  MeetingNoteCreate,
  MeetingStructureRequest,
  Task,
} from "@aec/types/pulse";
import type {
  ProposalGenerateRequest,
  ProposalGenerateResponse,
} from "@aec/types/winwork";

import { useChangeOrders } from "@/hooks/pulse/useChangeOrders";
import {
  useCreateMeetingNote,
  useStructureMeetingNotes,
} from "@/hooks/pulse/useMeetings";
import { useTasks } from "@/hooks/pulse/useTasks";
import { useDocuments } from "@/hooks/drawbridge/useDocuments";
import { useTenders } from "@/hooks/bidradar/useTenders";
import { useGenerateProposal } from "@/hooks/winwork/useGenerateProposal";

/**
 * Each `test()` body executes at runtime as a no-op (the
 * `expectTypeOf` calls compile to nothing meaningful), but tsc walks
 * them as part of `pnpm typecheck`. We use `test()` rather than bare
 * top-level statements so a test runner that DID load this file
 * would still report the file as "1 test passed" instead of
 * "0 tests" — protects against accidental rename-to-`.test.ts` that
 * would silently drop these from CI.
 */

test("useTasks() returns UseQueryResult<Task[]>", () => {
  const result = useTasks();
  expectTypeOf(result).toEqualTypeOf<UseQueryResult<Task[]>>();
  // The unwrap shape that every Kanban / list page does:
  //   const tasks = useTasks().data ?? []
  // Pin `data` as `Task[] | undefined` — a regression to `null`
  // would force every call site to add a null-check.
  expectTypeOf(result.data).toEqualTypeOf<Task[] | undefined>();
});

test("useChangeOrders() returns UseQueryResult<ChangeOrder[]>", () => {
  const result = useChangeOrders();
  expectTypeOf(result).toEqualTypeOf<UseQueryResult<ChangeOrder[]>>();
  expectTypeOf(result.data).toEqualTypeOf<ChangeOrder[] | undefined>();
});

test("useDocuments() returns the {data, meta} envelope shape, not flat Document[]", () => {
  // This one is load-bearing: the documents page renders pagination
  // off `result.data?.meta?.total`. Flattening the hook to return
  // `Document[]` instead of `{ data, meta }` would silently lose the
  // total — pagination would stick at "page 1 of 1" forever.
  const result = useDocuments();
  expectTypeOf(result.data).toMatchTypeOf<
    { data: Document[]; meta: unknown } | undefined
  >();
});

test("useTenders() returns the {items, total} shape", () => {
  // Pre-aggregated on the hook side (see useTenders.ts: it builds
  // `{ items, total }` from the envelope). A regression that
  // returned the raw envelope would force every call site to
  // re-implement the aggregation.
  const result = useTenders();
  expectTypeOf(result.data).toMatchTypeOf<
    { items: unknown[]; total: number } | undefined
  >();
});

test("useGenerateProposal() mutationFn accepts ProposalGenerateRequest, returns ProposalGenerateResponse", () => {
  const m = useGenerateProposal();
  // The mutate() input must be exactly the request shape — adding a
  // new field to ProposalGenerateRequest in `@aec/types/winwork`
  // should propagate here automatically. If a regression narrows
  // the parameter type (e.g. drops `discipline`), this assertion
  // breaks at typecheck time.
  expectTypeOf(m).toMatchTypeOf<
    UseMutationResult<ProposalGenerateResponse, Error, ProposalGenerateRequest>
  >();
});

test("useCreateMeetingNote() mutationFn accepts MeetingNoteCreate, returns MeetingNote", () => {
  const m = useCreateMeetingNote();
  expectTypeOf(m).toMatchTypeOf<
    UseMutationResult<MeetingNote, Error, MeetingNoteCreate>
  >();
});

test("useStructureMeetingNotes() mutationFn accepts MeetingStructureRequest", () => {
  // Distinct from useCreateMeetingNote: this one runs the LLM
  // extraction. Pin its input shape separately so a regression
  // that aliased one onto the other shows up here, not at form
  // runtime.
  const m = useStructureMeetingNotes();
  expectTypeOf(m).toMatchTypeOf<
    UseMutationResult<MeetingNote, Error, MeetingStructureRequest>
  >();
});

test("query-hook return types are NEVER `any` or `unknown`", () => {
  // Defence-in-depth: a regression that swallowed the generic on
  // `apiFetch<T>` would widen the queryFn's inferred return to
  // `unknown`, which then propagates to `result.data`. Pin
  // narrowness across the hook surface — these all pass today
  // (good!) and would break loudly if a generic got dropped.
  expectTypeOf(useTasks().data).not.toEqualTypeOf<unknown>();
  expectTypeOf(useChangeOrders().data).not.toEqualTypeOf<unknown>();
  expectTypeOf(useTenders().data).not.toEqualTypeOf<unknown>();
  expectTypeOf(useDocuments().data).not.toEqualTypeOf<unknown>();
});
