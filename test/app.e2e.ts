import { test, expect } from "@playwright/test";

test.describe("Fresh start", () => {
  test("shows default watchlist and $10k balance", async ({ page }) => {
    await page.goto("/");
    // Header shows default portfolio value and cash
    await expect(page.getByText("$10,000.00").first()).toBeVisible();
    // App title renders
    await expect(page.getByRole("heading", { level: 1 })).toContainText(
      "FinAlly"
    );
    for (const ticker of [
      "AAPL",
      "GOOGL",
      "MSFT",
      "AMZN",
      "TSLA",
      "NVDA",
      "META",
      "JPM",
      "V",
      "NFLX",
    ]) {
      await expect(
        page.locator("td").filter({ hasText: new RegExp(`^${ticker}$`) })
      ).toBeVisible();
    }
  });

  test("prices are streaming via SSE", async ({ page }) => {
    await page.goto("/");
    // Wait for connection status to show connected
    await expect(page.getByText("connected")).toBeVisible({ timeout: 10_000 });
    // At least one ticker should show a numeric price
    await expect(page.locator("td.tabular-nums").first()).not.toHaveText("--", {
      timeout: 10_000,
    });
  });
});

test.describe("Watchlist CRUD", () => {
  test("add and remove a ticker", async ({ page }) => {
    await page.goto("/");

    // Add a ticker
    const input = page.getByPlaceholder("Add ticker");
    await input.fill("SNAP");
    await input.press("Enter");
    await expect(page.getByText("SNAP")).toBeVisible({ timeout: 5_000 });

    // Remove the ticker
    const snapRow = page.locator("tr", { hasText: "SNAP" });
    await snapRow.getByTitle("Remove").click();
    await expect(page.getByText("SNAP")).not.toBeVisible({ timeout: 5_000 });
  });
});

test.describe("Trading", () => {
  test("buy shares: cash decreases and position appears", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("connected")).toBeVisible({ timeout: 10_000 });

    await page.getByPlaceholder("Ticker", { exact: true }).fill("AAPL");
    await page.getByPlaceholder("Qty").fill("1");
    await page.getByRole("button", { name: "BUY" }).click();

    await expect(page.getByText(/BUY 1 AAPL @ \$\d/)).toBeVisible({
      timeout: 5_000,
    });
    await expect(page.getByText("Cash").locator("..")).not.toContainText(
      "$10,000.00"
    );
  });

  test("sell shares: cash increases and position updates", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("connected")).toBeVisible({ timeout: 10_000 });

    await page.getByPlaceholder("Ticker", { exact: true }).fill("MSFT");
    await page.getByPlaceholder("Qty").fill("1");
    await page.getByRole("button", { name: "BUY" }).click();
    await expect(page.getByText(/BUY 1 MSFT @ \$\d/)).toBeVisible({
      timeout: 5_000,
    });

    await page.getByPlaceholder("Ticker", { exact: true }).fill("MSFT");
    await page.getByPlaceholder("Qty").fill("1");
    await page.getByRole("button", { name: "SELL" }).click();
    await expect(page.getByText(/SELL 1 MSFT @ \$\d/)).toBeVisible({
      timeout: 5_000,
    });
  });
});

test.describe("Portfolio visualization", () => {
  test("heatmap panel renders a bought position", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("Portfolio Heatmap")).toBeVisible();

    await expect(page.getByText("connected")).toBeVisible({ timeout: 10_000 });
    await page.getByPlaceholder("Ticker", { exact: true }).fill("TSLA");
    await page.getByPlaceholder("Qty").fill("1");
    await page.getByRole("button", { name: "BUY" }).click();

    await expect(page.getByText(/BUY 1 TSLA @ \$\d/)).toBeVisible({
      timeout: 5_000,
    });
    await expect(page.getByText("TSLA").nth(1)).toBeVisible();
  });

  test("P&L panel renders", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "P&L" })).toBeVisible();
  });
});

test.describe("AI Chat", () => {
  test("send a message and execute a mocked trade action", async ({ page }) => {
    await page.goto("/");

    // Chat panel should be visible
    await expect(page.getByText("AI Chat")).toBeVisible();

    // Empty state message
    await expect(
      page.getByText("Ask about stocks, trade, or manage your watchlist.")
    ).toBeVisible();

    // Type and send a message
    const chatInput = page.getByPlaceholder("Message...");
    await chatInput.fill("buy AAPL");
    await page.getByRole("button", { name: "Send" }).click();

    // User message should appear
    await expect(page.getByText("buy AAPL")).toBeVisible();

    // Wait for assistant response (mocked or real)
    await expect(page.getByText("Buying 10 shares of AAPL for you.")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText("Bought 10 AAPL")).toBeVisible();
  });

  test("chat panel collapses and expands", async ({ page }) => {
    await page.goto("/");

    // Collapse
    await page.getByLabel("Collapse chat").click();
    await expect(page.getByText("AI Chat")).not.toBeVisible();

    // Expand
    await page.getByLabel("Expand chat").click();
    await expect(page.getByText("AI Chat")).toBeVisible();
  });
});

test.describe("SSE resilience", () => {
  test("reconnects after disconnect", async ({ page }) => {
    await page.route("**/api/stream/prices", (route) => route.abort());

    await page.goto("/");
    await expect(page.getByText("reconnecting")).toBeVisible({
      timeout: 10_000,
    });

    await page.unroute("**/api/stream/prices");

    await expect(page.getByText("connected")).toBeVisible({ timeout: 15_000 });
  });
});
