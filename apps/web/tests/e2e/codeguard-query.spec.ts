import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: CODEGUARD Q&A page.
 *
 * What's covered
 * --------------
 * 1. Happy path — user types a question, clicks "Gửi". The POST body matches
 *    the input. Answer text + per-citation regulation/section/excerpt + the
 *    confidence percent all render.
 * 2. Abstain path — backend returns `confidence=0, citations=[], related_questions=[]`
 *    (the canned shape produced by `_abstain_response` in the pipeline when
 *    retrieval is empty). The UI must show the amber "Không có kết quả phù hợp"
 *    card, NOT the citation block. This is the load-bearing UX contract from
 *    the most recent round — confidence===0 + no citations is the abstain
 *    signal, anything else is a real answer.
 * 3. Related-question button — clicking a "Câu hỏi liên quan" entry fires a
 *    second POST with that question text. They look like links and must
 *    actually behave like buttons (regression target: a previous version of
 *    the page rendered them as inert <li>).
 * 4. Error path — when the mutation rejects, the assistant turn shows
 *    "Lỗi: ..." instead of crashing.
 */

test.describe("CODEGUARD / Query", () => {
  test("submits a question and renders the answer with grounded citations", async ({ page }) => {
    let lastBody: unknown = null;

    await page.route("**/api/v1/codeguard/query", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      lastBody = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            answer:
              "Hành lang thoát nạn trong nhà chung cư phải có chiều rộng tối thiểu 1.4 m.",
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
          meta: null,
          errors: null,
        }),
      });
    });

    await page.goto("/codeguard/query");

    // Submit is disabled with an empty textbox.
    const sendButton = page.getByRole("button", { name: /gửi/i });
    await expect(sendButton).toBeDisabled();

    const questionInput = page.getByPlaceholder(
      /Đặt câu hỏi về QCVN, TCVN, luật xây dựng/i,
    );
    await questionInput.fill("Chiều rộng tối thiểu của hành lang thoát nạn?");
    await expect(sendButton).toBeEnabled();

    await sendButton.click();

    // User turn renders immediately (setTurns is synchronous).
    await expect(
      page.getByText("Chiều rộng tối thiểu của hành lang thoát nạn?"),
    ).toBeVisible();

    // Assistant answer.
    await expect(
      page.getByText(/Hành lang thoát nạn trong nhà chung cư/),
    ).toBeVisible();

    // CitationCard surfaces the regulation code, the section ref (with §),
    // and the excerpt as a blockquote.
    await expect(page.getByText("QCVN 06:2022/BXD")).toBeVisible();
    await expect(page.getByText(/§\s*3\.2\.1/)).toBeVisible();
    await expect(page.getByText("không được nhỏ hơn 1.4 m")).toBeVisible();

    // Confidence rendered as a rounded percent (88%).
    await expect(page.getByText("88%")).toBeVisible();

    // Related-questions list is present.
    await expect(page.getByText("Câu hỏi liên quan")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Chiều rộng cầu thang thoát nạn?" }),
    ).toBeVisible();

    // Network contract: POST carried exactly the typed question.
    expect(lastBody).toMatchObject({
      question: "Chiều rộng tối thiểu của hành lang thoát nạn?",
    });
  });

  test("renders the abstain card when the backend returns confidence=0 with no citations", async ({
    page,
  }) => {
    // The pipeline's `_abstain_response` shape — what `node_generate` returns
    // when retrieval is empty. The UI must distinguish this from a normal
    // low-confidence answer.
    await page.route("**/api/v1/codeguard/query", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            answer:
              "Không tìm thấy quy định liên quan trong cơ sở tri thức CODEGUARD.",
            confidence: 0,
            citations: [],
            related_questions: [],
            check_id: "33333333-3333-3333-3333-333333333333",
          },
          meta: null,
          errors: null,
        }),
      });
    });

    await page.goto("/codeguard/query");
    await page
      .getByPlaceholder(/Đặt câu hỏi về QCVN, TCVN, luật xây dựng/i)
      .fill("Question that has no match in the corpus.");
    await page.getByRole("button", { name: /gửi/i }).click();

    // The amber "no result" card has its own banner — present in abstain,
    // absent in a real answer.
    await expect(page.getByText("Không có kết quả phù hợp")).toBeVisible();
    await expect(
      page.getByText(/Không tìm thấy quy định liên quan/),
    ).toBeVisible();

    // Abstain MUST NOT render the confidence bar or related-questions list.
    // (Both are scoped to the non-abstain branch in AssistantTurn.)
    await expect(page.getByText("Độ tin cậy:")).toHaveCount(0);
    await expect(page.getByText("Câu hỏi liên quan")).toHaveCount(0);
  });

  test("clicking a related question fires a follow-up query with that text", async ({
    page,
  }) => {
    const requests: string[] = [];

    await page.route("**/api/v1/codeguard/query", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      const body = route.request().postDataJSON() as { question: string };
      requests.push(body.question);

      // First call: return a response with two related questions. Second
      // call (after the user clicks one): return a different answer so we
      // can confirm a fresh round-trip happened.
      const isFollowUp = requests.length > 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            answer: isFollowUp
              ? "Cầu thang thoát nạn phải có chiều rộng ít nhất 1.0 m."
              : "Hành lang thoát nạn rộng tối thiểu 1.4 m.",
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
            related_questions: isFollowUp
              ? []
              : ["Chiều rộng cầu thang thoát nạn?"],
            check_id: null,
          },
          meta: null,
          errors: null,
        }),
      });
    });

    await page.goto("/codeguard/query");
    await page
      .getByPlaceholder(/Đặt câu hỏi về QCVN, TCVN, luật xây dựng/i)
      .fill("Chiều rộng hành lang?");
    await page.getByRole("button", { name: /gửi/i }).click();

    // Wait for the first answer + the related-question button to appear.
    const relatedButton = page.getByRole("button", {
      name: "Chiều rộng cầu thang thoát nạn?",
    });
    await expect(relatedButton).toBeVisible();

    // Click the related question — should fire a fresh POST with that text
    // (regression target: rendered as inert <li> in a previous revision).
    await relatedButton.click();

    // Second answer renders.
    await expect(
      page.getByText(/Cầu thang thoát nạn phải có chiều rộng/),
    ).toBeVisible();

    // Two requests fired, second one carried the related-question text.
    expect(requests).toHaveLength(2);
    expect(requests[1]).toBe("Chiều rộng cầu thang thoát nạn?");
  });

  test("renders an error turn when the query fails", async ({ page }) => {
    await page.route("**/api/v1/codeguard/query", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 502,
        contentType: "application/json",
        body: JSON.stringify({
          data: null,
          meta: null,
          errors: [{ code: "bad_gateway", message: "Q&A pipeline failed" }],
        }),
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
});
