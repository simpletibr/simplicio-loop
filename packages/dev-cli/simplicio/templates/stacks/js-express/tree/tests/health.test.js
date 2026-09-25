import assert from "node:assert/strict";
import test from "node:test";

import { createApp } from "../src/app.js";

test("health route responds with json", async () => {
  const app = createApp();
  const server = app.listen(0);
  try {
    const port = server.address().port;
    const response = await fetch(`http://127.0.0.1:${port}/health`);

    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { ok: true });
  } finally {
    server.close();
  }
});
