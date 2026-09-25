import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  it("renders the project name", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "{project_name}" })).toBeTruthy();
  });
});
