import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: CODEGUARD regulations browser (list + detail).
 *
 * The regulations page is read-only — no mutations to test, just the
 * three states every read-only surface has: loading, success, empty,
 * and error. Plus the navigation handoff to `/regulations/[id]`.
 *
 * Coverage
 * --------
 * 1. List renders — search returns rows, each row is a Link to the
 *    detail page; category badge + jurisdiction + effective_date
 *    surface in the row.
 * 2. Filtered-empty advisory — searching for something that returns
 *    `data: []` shows the amber "Không có kết quả phù hợp" card with
 *    actionable copy. Distinguishes "your filter matched nothing" from
 *    a misconfigured corpus.
 * 3. Unfiltered-empty hint — no search + empty corpus shows the seed
 *    instruction. Different state from #2.
 * 4. Error banner — 500 on the list endpoint surfaces a red banner
 *    rather than silently rendering "no results."
 * 5. Detail page renders — loads a single regulation by id, shows
 *    code_name + jurisdiction + sections.
 * 6. Detail 404 advisory — unknown UUID renders the amber "không tìm
 *    thấy" card, not a generic error.
 */

const REG_ID = "11111111-1111-1111-1111-111111111111";

test.describe("CODEGUARD / Regulations", () => {
  test("lists regulations with category badges + links to detail page", async ({ page }) => {
    await page.route("**/api/v1/codeguard/regulations*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: [
            {
              id: REG_ID,
              country_code: "VN",
              jurisdiction: "national",
              code_name: "QCVN 06:2022/BXD",
              category: "fire_safety",
              effective_date: "2022-10-25",
              expiry_date: null,
              source_url: null,
              language: "vi",
            },
            {
              id: "22222222-2222-2222-2222-222222222222",
              country_code: "VN",
              jurisdiction: "national",
              code_name: "QCVN 10:2014/BXD",
              category: "accessibility",
              effective_date: null,
              expiry_date: null,
              source_url: null,
              language: "vi",
            },
          ],
          meta: { page: 1, per_page: 50, total: 2 },
          errors: null,
        }),
      });
    });

    await page.goto("/codeguard/regulations");

    await expect(page.getByText("QCVN 06:2022/BXD")).toBeVisible();
    await expect(page.getByText("QCVN 10:2014/BXD")).toBeVisible();
    // Category labels also appear in the dropdown's <option> list, so
    // scope the badge assertion to the list <li> for the row to avoid
    // strict-mode collisions.
    const fireRow = page.getByRole("listitem").filter({ hasText: "QCVN 06:2022/BXD" });
    await expect(fireRow.getByText("PCCC")).toBeVisible();
    const accessRow = page.getByRole("listitem").filter({ hasText: "QCVN 10:2014/BXD" });
    await expect(accessRow.getByText("Tiếp cận")).toBeVisible();
    // Effective date string surfaces in the row metadata.
    await expect(page.getByText(/Hiệu lực 2022-10-25/)).toBeVisible();

    // Each row is a link to the detail page.
    const link = page.getByRole("link", { name: /QCVN 06:2022\/BXD/ });
    await expect(link).toHaveAttribute("href", `/codeguard/regulations/${REG_ID}`);
  });

  test("renders the amber filtered-empty advisory when a filter matches nothing", async ({
    page,
  }) => {
    await page.route("**/api/v1/codeguard/regulations*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: [],
          meta: { page: 1, per_page: 50, total: 0 },
          errors: null,
        }),
      });
    });

    await page.goto("/codeguard/regulations");
    // Pick a category filter — that's the simplest way to put the page
    // into "has filter" state without needing a debounced search input.
    await page.locator("select").selectOption("fire_safety");

    await expect(page.getByText("Không có kết quả phù hợp")).toBeVisible();
    await expect(page.getByText(/Hãy thử bỏ một điều kiện/)).toBeVisible();
  });

  test("renders the seed hint when the corpus itself is empty (no filter)", async ({ page }) => {
    await page.route("**/api/v1/codeguard/regulations*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: [],
          meta: { page: 1, per_page: 50, total: 0 },
          errors: null,
        }),
      });
    });

    await page.goto("/codeguard/regulations");
    // No filter set; landing page should hint at `make seed-codeguard`.
    await expect(page.getByText(/Thư viện chưa có quy chuẩn nào/)).toBeVisible();
    await expect(page.getByText("make seed-codeguard")).toBeVisible();
  });

  test("shows a red error banner when the list endpoint returns 500", async ({ page }) => {
    await page.route("**/api/v1/codeguard/regulations*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({
          data: null,
          meta: null,
          errors: [{ code: "internal", message: "DB unreachable" }],
        }),
      });
    });

    await page.goto("/codeguard/regulations");

    await expect(page.getByText("Lỗi khi tải thư viện quy chuẩn")).toBeVisible({ timeout: 3000 });
    await expect(page.getByText(/DB unreachable/)).toBeVisible();
  });

  test("detail page renders code_name + jurisdiction + sections", async ({ page }) => {
    await page.route(`**/api/v1/codeguard/regulations/${REG_ID}`, async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            id: REG_ID,
            country_code: "VN",
            jurisdiction: "national",
            code_name: "QCVN 06:2022/BXD",
            category: "fire_safety",
            effective_date: "2022-10-25",
            expiry_date: null,
            source_url: "https://example.gov.vn/qcvn06",
            language: "vi",
            content: null,
            sections: [
              {
                section_ref: "3.2.1",
                title: "Chiều rộng hành lang",
                content: "Hành lang thoát nạn không nhỏ hơn 1.4 m.",
              },
              {
                section_ref: "3.1",
                title: null,
                content: "Số lượng lối thoát nạn tối thiểu trên mỗi tầng.",
              },
            ],
          },
          meta: null,
          errors: null,
        }),
      });
    });

    await page.goto(`/codeguard/regulations/${REG_ID}`);

    await expect(page.getByRole("heading", { name: "QCVN 06:2022/BXD" })).toBeVisible();
    await expect(page.getByText(/Hiệu lực 2022-10-25/)).toBeVisible();
    // Source link uses the source_url.
    await expect(page.getByRole("link", { name: /Nguồn/ })).toHaveAttribute(
      "href",
      "https://example.gov.vn/qcvn06",
    );
    // Section count + body content surface.
    await expect(page.getByText(/Nội dung \(2 mục\)/)).toBeVisible();
    await expect(page.getByText("3.2.1")).toBeVisible();
    await expect(page.getByText("Chiều rộng hành lang")).toBeVisible();
    await expect(
      page.getByText("Hành lang thoát nạn không nhỏ hơn 1.4 m."),
    ).toBeVisible();
  });

  test("detail page renders the 'không tìm thấy' advisory on 404", async ({ page }) => {
    await page.route(`**/api/v1/codeguard/regulations/${REG_ID}`, async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({
          data: null,
          meta: null,
          errors: [{ code: "not_found", message: "Regulation not found" }],
        }),
      });
    });

    await page.goto(`/codeguard/regulations/${REG_ID}`);

    // Amber advisory rather than the red error banner — different
    // failure class, different visual treatment.
    await expect(page.getByText("Không tìm thấy quy chuẩn")).toBeVisible({ timeout: 3000 });
    await expect(page.getByText(/đã bị xóa khỏi thư viện/)).toBeVisible();
    // Back link is reachable so the user isn't stranded.
    await expect(page.getByRole("link", { name: /Quay lại thư viện/ })).toBeVisible();
  });
});
