import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock the theme store before importing formatTime
vi.mock("../stores/theme", () => {
  let format = "relative";
  return {
    timeFormat: () => format,
    __setFormat: (f: string) => { format = f; },
  };
});

import { formatTimestamp } from "./formatTime";

// Helper to get the mock setter
async function setTimeFormat(fmt: string) {
  const mod = await import("../stores/theme") as any;
  mod.__setFormat(fmt);
}

const mockT = (key: string) => {
  const map: Record<string, string> = {
    "time.justNow": "just now",
    "time.minutesAgo": "{n}m ago",
    "time.hoursAgo": "{n}h ago",
    "time.daysAgo": "{n}d ago",
    "time.monthsAgo": "{n}mo ago",
    "time.yearsAgo": "{n}y ago",
    "time.remainingSeconds": "{n}s left",
    "time.remainingMinutes": "{n}m left",
    "time.remainingHours": "{n}h left",
    "time.remainingDays": "{n}d left",
    "time.futureSeconds": "in {n}s",
    "time.futureMinutes": "in {n}m",
    "time.futureHours": "in {n}h",
    "time.futureDays": "in {n}d",
  };
  return map[key] ?? key;
};

describe("formatTimestamp", () => {
  describe("absolute format", () => {
    beforeEach(async () => { await setTimeFormat("absolute"); });

    it("formats as YYYY-MM-DD HH:MM:SS", () => {
      const result = formatTimestamp("2024-03-15T10:30:45Z", mockT);
      // The output depends on local timezone, but format should be correct
      expect(result).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
    });

    it("formats date-only when dateOnly is true", () => {
      const result = formatTimestamp("2024-03-15T10:30:45Z", mockT, true);
      expect(result).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    });
  });

  describe("relative format", () => {
    beforeEach(async () => { await setTimeFormat("relative"); });

    it("shows 'just now' for recent timestamps", () => {
      const now = new Date().toISOString();
      expect(formatTimestamp(now, mockT)).toBe("just now");
    });

    it("shows minutes ago", () => {
      const fiveMinAgo = new Date(Date.now() - 5 * 60 * 1000).toISOString();
      expect(formatTimestamp(fiveMinAgo, mockT)).toBe("5m ago");
    });

    it("shows hours ago", () => {
      const threeHoursAgo = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString();
      expect(formatTimestamp(threeHoursAgo, mockT)).toBe("3h ago");
    });

    it("shows days ago", () => {
      const twoDaysAgo = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString();
      expect(formatTimestamp(twoDaysAgo, mockT)).toBe("2d ago");
    });

    it("shows months ago", () => {
      const threeMonthsAgo = new Date(Date.now() - 90 * 24 * 60 * 60 * 1000).toISOString();
      expect(formatTimestamp(threeMonthsAgo, mockT)).toBe("3mo ago");
    });

    it("shows years ago", () => {
      const twoYearsAgo = new Date(Date.now() - 730 * 24 * 60 * 60 * 1000).toISOString();
      expect(formatTimestamp(twoYearsAgo, mockT)).toBe("2y ago");
    });

    it("handles future dates as 'in Xm'", () => {
      const fiveMinFuture = new Date(Date.now() + 5 * 60 * 1000).toISOString();
      expect(formatTimestamp(fiveMinFuture, mockT)).toBe("in 5m");
    });

    it("handles countdown future dates as 'Xm left'", () => {
      const fiveMinFuture = new Date(Date.now() + 5 * 60 * 1000).toISOString();
      expect(formatTimestamp(fiveMinFuture, mockT, false, true)).toBe("5m left");
    });
  });

  describe("combined format", () => {
    beforeEach(async () => { await setTimeFormat("combined"); });

    it("shows both absolute and relative", () => {
      const now = new Date().toISOString();
      const result = formatTimestamp(now, mockT);
      // Should contain both absolute date and relative text
      expect(result).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \(just now\)$/);
    });
  });

  describe("unixtime format", () => {
    beforeEach(async () => { await setTimeFormat("unixtime"); });

    it("shows unix timestamp", () => {
      const result = formatTimestamp("2024-01-01T00:00:00Z", mockT);
      expect(result).toBe(String(Math.floor(new Date("2024-01-01T00:00:00Z").getTime() / 1000)));
    });
  });
});
