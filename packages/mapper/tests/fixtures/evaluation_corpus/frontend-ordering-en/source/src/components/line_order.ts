export type Lane = { kind: "structural" | "temporal"; startDate: string; name: string };

export function orderLanes(lanes: Lane[]): Lane[] {
  const priority = { structural: 0, temporal: 1 } as const;
  return [...lanes].sort((left, right) => priority[left.kind] - priority[right.kind] || left.startDate.localeCompare(right.startDate));
}
