/**
 * Public entrypoint for `@aec/sdk`. Composes the hand-written
 * client core with the auto-generated operations table.
 *
 * Usage:
 *
 *   import { AecClient } from "@aec/sdk";
 *
 *   const client = new AecClient({ apiKey: process.env.AEC_API_KEY! });
 *   const projects = await client.list_projects_api_v1_projects_get({}, { status: "construction" });
 *
 * Method names track FastAPI's `operationId`. Re-running
 * `pnpm --filter @aec/sdk run generate` after the backend deploys
 * picks up new routes + dropped routes automatically.
 */

import { AecClientCore } from "./client";
import { bindOperations } from "./generated";


export type { AecClientOptions, Envelope } from "./client";
export { AecApiError } from "./client";


export class AecClient {
  // The bound operations are the API surface partners call. The
  // class wraps the core + ops together so `new AecClient(opts)` is
  // the only thing exported — partners shouldn't need to know about
  // `AecClientCore` or `bindOperations` separately.
  readonly ops: ReturnType<typeof bindOperations>;

  constructor(opts: ConstructorParameters<typeof AecClientCore>[0]) {
    const core = new AecClientCore(opts);
    this.ops = bindOperations(core);
  }
}
