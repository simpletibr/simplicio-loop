export type OrderDraft = {
  subtotal: number;
  discount: number;
  taxRate: number;
};

export function buildCheckoutPayload(draft: OrderDraft): { total: number; discount: number } {
  const discounted = draft.subtotal - draft.discount;
  const total = Number((discounted * (1 + draft.taxRate)).toFixed(2));
  return { total, discount: draft.discount };
}
