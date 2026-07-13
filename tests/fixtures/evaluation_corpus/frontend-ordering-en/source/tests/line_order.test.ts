import {orderLanes} from "../src/components/line_order";

test("structural lanes come first", () => {
  const ordered = orderLanes([
    {kind: "temporal", startDate: "2024-03-01", name: "T1"},
    {kind: "structural", startDate: "2024-01-01", name: "S1"},
  ]);
  expect(ordered.map((lane) => lane.name)).toEqual(["S1", "T1"]);
});
