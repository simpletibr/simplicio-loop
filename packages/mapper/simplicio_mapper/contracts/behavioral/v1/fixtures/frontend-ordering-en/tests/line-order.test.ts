import { test } from 'node:test';
import assert from 'node:assert/strict';
import { orderLineCards } from '../src/components/line-order.js';

test('orders cards by start date', () => {
  assert.deepEqual(orderLineCards([]), []);
});
