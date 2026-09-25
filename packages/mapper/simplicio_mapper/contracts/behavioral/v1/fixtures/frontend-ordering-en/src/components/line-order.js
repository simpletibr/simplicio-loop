export function orderLineCards(cards) {
  return [...cards].sort((left, right) => left.startDate.localeCompare(right.startDate));
}
