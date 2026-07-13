import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import StatusBadge from "./StatusBadge";

describe("StatusBadge", () => {
  it("renders the localized status", () => {
    render(<StatusBadge status="completed" />);
    expect(screen.getByText("已完成")).toBeInTheDocument();
  });
});
