import { describe, expect, it } from "vitest";

import { loader } from "./health";

describe("health loader", () => {
  it("returns ok", async () => {
    const response = await loader();

    expect(await response.json()).toEqual({ ok: true });
  });
});
