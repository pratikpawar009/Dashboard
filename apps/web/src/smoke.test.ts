import { describe, expect, it } from "vitest";

describe("smoke", () => {
  it("proves the vitest runner is wired", () => {
    expect(1 + 1).toBe(2);
  });
});
