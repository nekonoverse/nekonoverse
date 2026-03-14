import { describe, it, expect } from "vitest";
import { focalPointToObjectPosition } from "./focalPoint";

describe("focalPointToObjectPosition", () => {
  it("returns undefined for null focus", () => {
    expect(focalPointToObjectPosition(null)).toBeUndefined();
  });

  it("returns undefined for undefined focus", () => {
    expect(focalPointToObjectPosition(undefined)).toBeUndefined();
  });

  it("converts center (0, 0) to 50% 50%", () => {
    expect(focalPointToObjectPosition({ x: 0, y: 0 })).toBe("50.0% 50.0%");
  });

  it("converts top-left (-1, 1) to 0% 0%", () => {
    expect(focalPointToObjectPosition({ x: -1, y: 1 })).toBe("0.0% 0.0%");
  });

  it("converts bottom-right (1, -1) to 100% 100%", () => {
    expect(focalPointToObjectPosition({ x: 1, y: -1 })).toBe("100.0% 100.0%");
  });

  it("converts top-right (1, 1) to 100% 0%", () => {
    expect(focalPointToObjectPosition({ x: 1, y: 1 })).toBe("100.0% 0.0%");
  });

  it("converts bottom-left (-1, -1) to 0% 100%", () => {
    expect(focalPointToObjectPosition({ x: -1, y: -1 })).toBe("0.0% 100.0%");
  });

  it("handles fractional values", () => {
    // x=0.5 -> (0.5+1)/2*100 = 75%
    // y=0.5 -> (1-0.5)/2*100 = 25%
    expect(focalPointToObjectPosition({ x: 0.5, y: 0.5 })).toBe("75.0% 25.0%");
  });

  it("handles negative fractional values", () => {
    // x=-0.5 -> (-0.5+1)/2*100 = 25%
    // y=-0.5 -> (1-(-0.5))/2*100 = 75%
    expect(focalPointToObjectPosition({ x: -0.5, y: -0.5 })).toBe("25.0% 75.0%");
  });
});
