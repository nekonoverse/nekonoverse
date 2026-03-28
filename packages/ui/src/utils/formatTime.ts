import { createSignal } from "solid-js";
import { timeFormat } from "../stores/theme";

// Accept any translator function — i18n t() has (key: keyof Dictionary) => string
// but we build keys dynamically, so accept the widest compatible signature.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type TranslatorFn = (key: any) => string;

function formatAbsolute(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function formatAbsoluteDate(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function formatUnixtime(iso: string): string {
  return String(Math.floor(new Date(iso).getTime() / 1000));
}

export function formatRelative(iso: string, t: TranslatorFn, countdown = false): string {
  const now = Date.now();
  const then = new Date(iso).getTime();
  const diffSec = Math.floor((now - then) / 1000);

  // Future dates
  if (diffSec < 0) {
    const prefix = countdown ? "time.remaining" : "time.future";
    const futureSec = -diffSec;
    if (futureSec < 60) return t(`${prefix}Seconds`).replace("{n}", String(futureSec));

    const futureMin = Math.floor(futureSec / 60);
    if (futureMin < 60) return t(`${prefix}Minutes`).replace("{n}", String(futureMin));

    const futureHour = Math.floor(futureMin / 60);
    if (futureHour < 24) return t(`${prefix}Hours`).replace("{n}", String(futureHour));

    const futureDay = Math.floor(futureHour / 24);
    return t(`${prefix}Days`).replace("{n}", String(futureDay));
  }

  if (diffSec < 60) return t("time.justNow");

  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return t("time.minutesAgo").replace("{n}", String(diffMin));

  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return t("time.hoursAgo").replace("{n}", String(diffHour));

  const diffDay = Math.floor(diffHour / 24);
  if (diffDay < 30) return t("time.daysAgo").replace("{n}", String(diffDay));

  const diffMonth = Math.floor(diffDay / 30);
  if (diffMonth < 12) return t("time.monthsAgo").replace("{n}", String(diffMonth));

  const diffYear = Math.floor(diffDay / 365);
  return t("time.yearsAgo").replace("{n}", String(diffYear));
}

/**
 * Format a timestamp according to the user's chosen time format.
 * @param iso      ISO 8601 date string
 * @param t        i18n translation function
 * @param dateOnly If true, use date-only for absolute part (for profile joined dates)
 */
export function formatTimestamp(iso: string, t: TranslatorFn, dateOnly = false, countdown = false): string {
  const fmt = timeFormat();
  const abs = dateOnly ? formatAbsoluteDate(iso) : formatAbsolute(iso);

  switch (fmt) {
    case "absolute":
      return abs;
    case "relative":
      return formatRelative(iso, t, countdown);
    case "combined":
      return `${abs} (${formatRelative(iso, t, countdown)})`;
    case "unixtime":
      return formatUnixtime(iso);
    default:
      return abs;
  }
}

// Global tick signal for auto-updating relative times (every 60 seconds)
const [timeTick, setTimeTick] = createSignal(0);

if (typeof window !== "undefined") {
  setInterval(() => setTimeTick((n: number) => n + 1), 60_000);
}

/**
 * Call inside a reactive context to subscribe to the 60-second tick.
 * Triggers re-render so relative times stay up-to-date.
 */
export function useTimeTick(): number {
  return timeTick();
}
