const test = require("node:test");
const assert = require("node:assert");
const { greet } = require("../src/index.js");

test("greet returns a greeting", () => {
  assert.strictEqual(greet("x"), "Hello, x!");
});
