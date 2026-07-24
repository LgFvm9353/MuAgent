const timezoneSuffix = /(Z|[+-]\d{2}:?\d{2})$/i

export function parseApiDate(value: string): Date {
  const normalized = timezoneSuffix.test(value) ? value : `${value}Z`
  return new Date(normalized)
}

export function apiDateTimestamp(value: string): number {
  return parseApiDate(value).getTime()
}
