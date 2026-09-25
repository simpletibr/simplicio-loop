import { buildCheckoutPayload } from "../src/frontend/order_form";

const payload = buildCheckoutPayload({ subtotal: 100, discount: 5, taxRate: 0.1 });

if (payload.total !== 104.5) {
  throw new Error(`expected 104.5, received ${payload.total}`);
}
