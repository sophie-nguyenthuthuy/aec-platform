import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: CODEGUARD Q&A page (streaming variant).
 *
 * The page now consumes `POST /api/v1/codeguard/query/stream` which
 * returns SSE — every test mocks that endpoint by returning a single
 * response with an SSE-framed body. Playwright's `route.fulfill()`
 * delivers the body in one chunk; the hook's parser handles
 * multi-event bodies correctly because events are `\n\n`-delimited.
 *
 * What's covered
 * --------------
 * 1. Happy path — token deltas accumulate into the answer; the final
 *    `done` event attaches citations + confidence + related-question
 *    buttons.
 * 2. Abstain — backend emits a single `done` with confidence=0 and no
 *    citations. UI renders the amber "Không có kết quả phù hợp" card.
 * 3. Related-question button — clicking a "Câu hỏi liên quan" entry
 *    fires another POST to /query/stream with the clicked question.
 * 4. Error — backend emits an `event: error` frame; the assistant turn
 *    shows "Lỗi: ..." instead of crashing.
 */

interface SseEvent {
  event: string;
  data: unknown;
}

/** Build an SSE-formatted body from a list of events. Mirrors the wire
 *  format the route layer produces. */
function sseBody(events: SseEvent[]): string {
  return events
    .map(({ event, data }) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)
    .join("");
}

test.describe("CODEGUARD / Query (streaming)", () => {
  test("streams token deltas and renders the final answer with citations", async ({ page }) => {
    let lastBody: unknown = null;

    await page.route("**/api/v1/codeguard/query/stream", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      lastBody = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: sseBody([
          { event: "token", data: { delta: "Hành lang " } },
          { event: "token", data: { delta: "thoát nạn " } },
          { event: "token", data: { delta: "rộng tối thiểu 1.4 m." } },
          {
            event: "done",
            data: {
              answer: "Hành lang thoát nạn rộng tối thiểu 1.4 m.",
              confidence: 0.88,
              citations: [
                {
                  regulation_id: "11111111-1111-1111-1111-111111111111",
                  regulation: "QCVN 06:2022/BXD",
                  section: "3.2.1",
                  excerpt: "không được nhỏ hơn 1.4 m",
                  source_url: "https://example.gov.vn/qcvn06",
                },
              ],
              related_questions: [
                "Chiều rộng cầu thang thoát nạn?",
                "Số lượng lối thoát nạn tối thiểu?",
              ],
              check_id: "22222222-2222-2222-2222-222222222222",
            },
          },
        ]),
      });
    });

    await page.goto("/codeguard/query");

    const sendButton = page.getByRole("button", { name: /gửi/i });
    await expect(sendButton).toBeDisabled();
    await page
      .getByPlaceholder(/Đặt câu hỏi về QCVN, TCVN, luật xây dựng/i)
      .fill("Chiều rộng tối thiểu của hành lang thoát nạn?");
    await expect(sendButton).toBeEnabled();
    await sendButton.click();

    // The user turn appears immediately.
    await expect(
      page.getByText("Chiều rộng tối thiểu của hành lang thoát nạn?"),
    ).toBeVisible();

    // The final answer text matches the `done` event's `answer` field
    // (which the page prefers over the accumulated tokens to handle the
    // abstain case uniformly).
    await expect(
      page.getByText("Hành lang thoát nạn rộng tối thiểu 1.4 m."),
    ).toBeVisible();

    // CitationCard surfaces regulation + section + excerpt.
    await expect(page.getByText("QCVN 06:2022/BXD")).toBeVisible();
    await expect(page.getByText(/§\s*3\.2\.1/)).toBeVisible();
    await expect(page.getByText("không được nhỏ hơn 1.4 m")).toBeVisible();

    // Confidence rendered as a percent.
    await expect(page.getByText("88%")).toBeVisible();

    // Related-questions list renders as buttons.
    await expect(
      page.getByRole("button", { name: "Chiều rộng cầu thang thoát nạn?" }),
    ).toBeVisible();

    // Network contract: the POST carried the typed question.
    expect(lastBody).toMatchObject({
      question: "Chiều rộng tối thiểu của hành lang thoát nạn?",
    });
  });

  test("renders the abstain card when done arrives with confidence=0 + no citations", async ({ page }) => {
    await page.route("**/api/v1/codeguard/query/stream", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        // Abstain path emits a single `done` and no token deltas — the
        // pipeline never invokes the LLM.
        body: sseBody([
          {
            event: "done",
            data: {
              answer: "Không tìm thấy quy định liên quan trong cơ sở tri thức CODEGUARD.",
              confidence: 0,
              citations: [],
              related_questions: [],
              check_id: "33333333-3333-3333-3333-333333333333",
            },
          },
        ]),
      });
    });

    await page.goto("/codeguard/query");
    await page
      .getByPlaceholder(/Đặt câu hỏi về QCVN, TCVN, luật xây dựng/i)
      .fill("Question with no match in the corpus.");
    await page.getByRole("button", { name: /gửi/i }).click();

    // Amber abstain card.
    await expect(page.getByText("Không có kết quả phù hợp")).toBeVisible();
    await expect(
      page.getByText(/Không tìm thấy quy định liên quan/),
    ).toBeVisible();

    // Abstain MUST NOT render the confidence bar or related questions.
    await expect(page.getByText("Độ tin cậy:")).toHaveCount(0);
    await expect(page.getByText("Câu hỏi liên quan")).toHaveCount(0);
  });

  test("clicking a related question fires another streaming query", async ({ page }) => {
    const requests: string[] = [];

    await page.route("**/api/v1/codeguard/query/stream", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      const body = route.request().postDataJSON() as { question: string };
      requests.push(body.question);

      const isFollowUp = requests.length > 1;
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: sseBody([
          { event: "token", data: { delta: isFollowUp ? "Cầu thang " : "Hành lang " } },
          { event: "token", data: { delta: isFollowUp ? "rộng 1.0 m." : "rộng 1.4 m." } },
          {
            event: "done",
            data: {
              answer: isFollowUp ? "Cầu thang rộng 1.0 m." : "Hành lang rộng 1.4 m.",
              confidence: 0.8,
              citations: [
                {
                  regulation_id: "11111111-1111-1111-1111-111111111111",
                  regulation: "QCVN 06:2022/BXD",
                  section: isFollowUp ? "3.2.2" : "3.2.1",
                  excerpt: isFollowUp ? "ít nhất 1.0 m" : "không nhỏ hơn 1.4 m",
                  source_url: null,
                },
              ],
              related_questions: isFollowUp ? [] : ["Chiều rộng cầu thang thoát nạn?"],
              check_id: null,
            },
          },
        ]),
      });
    });

    await page.goto("/codeguard/query");
    await page
      .getByPlaceholder(/Đặt câu hỏi về QCVN, TCVN, luật xây dựng/i)
      .fill("Chiều rộng hành lang?");
    await page.getByRole("button", { name: /gửi/i }).click();

    const relatedButton = page.getByRole("button", {
      name: "Chiều rộng cầu thang thoát nạn?",
    });
    await expect(relatedButton).toBeVisible();
    await relatedButton.click();

    // Second answer renders.
    await expect(page.getByText("Cầu thang rộng 1.0 m.")).toBeVisible();

    expect(requests).toHaveLength(2);
    expect(requests[1]).toBe("Chiều rộng cầu thang thoát nạn?");
  });

  test("renders an error turn when the stream emits an error event", async ({ page }) => {
    await page.route("**/api/v1/codeguard/query/stream", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        // Mid-stream errors are reported via an `error` event, not by
        // an HTTP-status failure. The connection is already 200 OK.
        body: sseBody([
          { event: "error", data: { message: "Q&A pipeline failed" } },
        ]),
      });
    });

    await page.goto("/codeguard/query");
    await page
      .getByPlaceholder(/Đặt câu hỏi về QCVN, TCVN, luật xây dựng/i)
      .fill("Câu hỏi sẽ thất bại");
    await page.getByRole("button", { name: /gửi/i }).click();

    await expect(page.getByText(/Lỗi:/)).toBeVisible({ timeout: 3000 });
    await expect(page.getByText(/Q&A pipeline failed/)).toBeVisible();
  });

  test("surfaces a non-200 HTTP error as an error turn", async ({ page }) => {
    // The streaming hook also has to gracefully handle the case where
    // the SSE response itself fails (502 from a proxy, auth failure,
    // etc.) — the route never produces a single SSE frame, so the hook
    // must extract a message from the envelope-shaped error body.
    await page.route("**/api/v1/codeguard/query/stream", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 502,
        contentType: "application/json",
        body: JSON.stringify({
          data: null,
          meta: null,
          errors: [{ code: "bad_gateway", message: "Upstream LLM unavailable" }],
        }),
      });
    });

    await page.goto("/codeguard/query");
    await page
      .getByPlaceholder(/Đặt câu hỏi về QCVN, TCVN, luật xây dựng/i)
      .fill("Câu hỏi sẽ trả về 502");
    await page.getByRole("button", { name: /gửi/i }).click();

    await expect(page.getByText(/Lỗi:/)).toBeVisible({ timeout: 3000 });
    await expect(page.getByText(/Upstream LLM unavailable/)).toBeVisible();
  });
});
