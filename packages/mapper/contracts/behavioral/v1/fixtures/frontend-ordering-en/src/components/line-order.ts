export function orderLineCards(cards: Array<{ kind: string; startDate: string }>) {
  return [...cards].sort((left, right) => left.startDate.localeCompare(right.startDate));
}
