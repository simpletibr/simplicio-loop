import { AppController } from "./app.controller";

describe("AppController", () => {
  it("returns health", () => {
    expect(new AppController().health()).toEqual({ ok: true });
  });
});
