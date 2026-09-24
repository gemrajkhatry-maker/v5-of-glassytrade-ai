import { expect, test } from "@playwright/test";


test("renders versioned runtime projection without order authority", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("runtime-status")).toHaveText("degraded");
  const authority = await page.evaluate(() => ({
    placeOrder: typeof (window as Window & { placeOrder?: unknown }).placeOrder,
    targetTrading: typeof (window as Window & { targetTrading?: unknown }).targetTrading,
  }));
  expect(authority).toEqual({ placeOrder: "undefined", targetTrading: "undefined" });
});
