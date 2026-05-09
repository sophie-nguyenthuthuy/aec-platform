# @aec/sdk

TypeScript client for the AEC Platform API. Auto-generated from
`/openapi.json` on every backend deploy + a small hand-written core
for retry, auth, and envelope unwrap.

## Usage

```ts
import { AecClient } from "@aec/sdk";

const client = new AecClient({
  apiKey: process.env.AEC_API_KEY!,
  // baseUrl: "https://api.aec-platform.vn",  // default
  // maxRetries: 3,                             // default
});

// Auto-generated method names follow FastAPI's `operationId`.
const projects = await client.ops.list_projects_api_v1_projects_get(
  {},                              // path params (empty for this route)
  { status: "construction" },      // query string
);
```

Errors throw `AecApiError`:

```ts
import { AecApiError } from "@aec/sdk";

try {
  await client.ops.create_webhook_api_v1_webhooks_post({}, undefined, {
    url: "https://example.com/hook",
    event_types: ["costpulse.estimate.approve"],
  });
} catch (err) {
  if (err instanceof AecApiError && err.status === 403) {
    console.error("Need admin role to create webhooks");
  }
  throw err;
}
```

## Retry semantics

The core retries automatically on:

* **429 Too Many Requests** — sleeps for `Retry-After` seconds (or 1s
  if the header is missing).
* **5xx** — exponential backoff with jitter, doubling each attempt
  starting at 500ms.

Both are bounded by `maxRetries` (default 3). Set to 0 to disable.

## Regenerating

The auto-generated methods live in `src/generated.ts`. To pick up
new backend routes:

```sh
AEC_OPENAPI_URL=https://api.aec-platform.vn/openapi.json \
  pnpm --filter @aec/sdk run generate
pnpm --filter @aec/sdk run build
```

The generator is a vanilla node script (no codegen library deps) —
see `scripts/generate.mjs`.

## Test mode

API keys minted with `mode: "test"` route to `/api/v1/sandbox/*`
fixture data instead of real tenant rows. Useful for integration
tests:

```ts
const sdk = new AecClient({
  apiKey: process.env.AEC_TEST_API_KEY!,
});
// Hit a sandbox endpoint directly — same auth, deterministic data.
const samples = await sdk.ops.list_sandbox_projects_api_v1_sandbox_projects_get({});
```
