import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: Drawbridge Q&A page.
 *
 * What's covered
 * --------------
 * 1. Submit flow — user types a project_id, types a question, clicks "Gửi".
 *    The POST /api/v1/drawbridge/query body reflects the input exactly.
 *    The rendered answer, confidence bar, and source-document excerpts
 *    appear.
 * 2. Submit is disabled until both project_id and question are set. This
 *    is the page's only client-side gate.
 * 3. Error path — when the API returns an error envelope, the assistant
 *    turn shows "Lỗi: ..." without crashing. The `catch` branch in the
 *    page is the only failure-handling path, so it's worth locking in.
 */

const PROJECT_ID = "11111111-1111-1111-1111-111111111111";

test.describe("Drawbridge / Query", () => {
  test("submits a question and renders the answer with sources", async ({ page }) => {
    let lastBody: unknown = null;

    await page.route("**/api/v1/drawbridge/query", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      lastBody = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            answer: "Độ dày sàn tầng 3 là 200mm theo bản vẽ kết cấu S-301.",
            confidence: 0.85,
            source_documents: [
              {
                document_id: "dddddddd-dddd-dddd-dddd-dddddddddddd",
                drawing_number: "S-301",
                title: "Level 3 slab plan",
                discipline: "structural",
                page: 2,
                excerpt: "SLAB THICKNESS = 200mm",
                bbox: null,
              },
            ],
            related_questions: ["Độ dày sàn tầng 4 là bao nhiêu?"],
          },
          meta: null,
          errors: null,
        }),
      });
    });

    await page.goto("/drawbridge/query");

    // Submit is disabled without a project_id and a question.
    const sendButton = page.getByRole("button", { name: /gửi/i });
    await expect(sendButton).toBeDisabled();

    await page.getByPlaceholder("project_id").fill(PROJECT_ID);
    await expect(sendButton).toBeDisabled(); // still no question yet

    const questionInput = page.getByPlaceholder(/Đặt câu hỏi về bản vẽ/i);
    await questionInput.fill("Độ dày sàn tầng 3 là bao nhiêu?");
    await expect(sendButton).toBeEnabled();

    await sendButton.click();

    // User turn renders immediately (setTurns runs before the await).
    await expect(
      page.getByText("Độ dày sàn tầng 3 là bao nhiêu?"),
    ).toBeVisible();

    // Assistant answer renders once the mutation resolves.
    await expect(
      page.getByText(/Độ dày sàn tầng 3 là 200mm/),
    ).toBeVisible();

    // Source-doc card renders drawing number, page, excerpt.
    // The drawing_number `S-301` also appears inside the answer text, so
    // scope to the exact-match span (which is what the card actually uses)
    // to avoid strict-mode ambiguity.
    await expect(page.getByText("S-301", { exact: true })).toBeVisible();
    await expect(page.getByText("p.2")).toBeVisible();
    await expect(page.getByText(/SLAB THICKNESS = 200mm/)).toBeVisible();

    // Confidence rendered as a percent (85%).
    await expect(page.getByText("85%")).toBeVisible();

    // Network contract: the POST carried exactly what the user typed.
    expect(lastBody).toMatchObject({
      project_id: PROJECT_ID,
      question: "Độ dày sàn tầng 3 là bao nhiêu?",
    });
  });

  test("renders an error turn when the query fails", async ({ page }) => {
    await page.route("**/api/v1/drawbridge/query", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({
          data: null,
          errors: [{ code: "internal", message: "model timed out" }],
        }),
      });
    });

    await page.goto("/drawbridge/query");
    await page.getByPlaceholder("project_id").fill(PROJECT_ID);
    await page
      .getByPlaceholder(/Đặt câu hỏi về bản vẽ/i)
      .fill("What is the column spacing?");
    await page.getByRole("button", { name: /gửi/i }).click();

    // Page catches the error and pushes an assistant turn starting with "Lỗi:".
    await expect(page.getByText(/Lỗi:/)).toBeVisible({ timeout: 3000 });
    await expect(page.getByText(/model timed out/)).toBeVisible();
  });
});
