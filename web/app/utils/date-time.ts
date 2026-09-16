const CHINA_TIME_ZONE = "Asia/Shanghai";
const EXPLICIT_TIME_ZONE = /(?:z|[+-]\d{2}:?\d{2})$/i;

export function parseApiDateTime(value: string): Date {
  // SQLite persists UTC as a timezone-naive ISO value. Browsers interpret such
  // strings as local time, so make the API contract explicit before formatting.
  return new Date(EXPLICIT_TIME_ZONE.test(value) ? value : `${value}Z`);
}

function chinaParts(value: string): Record<string, string> | null {
  const date = parseApiDateTime(value);
  if (Number.isNaN(date.getTime())) return null;
  return Object.fromEntries(
    new Intl.DateTimeFormat("zh-CN", {
      timeZone: CHINA_TIME_ZONE,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(date)
      .map((part) => [part.type, part.value]),
  );
}

export function formatChinaEventTime(value: string): string {
  const parts = chinaParts(value);
  return parts ? `${parts.hour}:${parts.minute}:${parts.second}` : value;
}

export function formatChinaDateTime(value?: string | null): string {
  if (!value) return "—";
  const parts = chinaParts(value);
  return parts
    ? `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`
    : value;
}
