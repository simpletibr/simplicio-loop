# Polyglot checkout flow

As a commerce operator
I want `buildCheckoutPayload` in `src/frontend/order_form.ts` and `normalize_checkout`
in `src/api/order_controller.py` to agree on the computed total
So the frontend handoff, backend normalization, and both verification routes stay aligned.

AC01: `buildCheckoutPayload` emits the same rounded total consumed by `normalize_checkout`.
AC02: `tests/order_form.test.ts` and `tests/test_order_controller.py` remain the verification route.
AC03: the retrieval pack keeps the frontend and backend implementation together without exceeding the token budget.
