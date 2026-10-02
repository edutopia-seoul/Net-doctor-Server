export const isNumber = value => typeof value === 'number' && Number.isFinite(value);

export const metricValue = (measurement, path) =>
  path.split('.').reduce((value, key) => value?.[key], measurement?.metrics);

export function chartPoints(measurements, path) {
  return measurements
    .map(measurement => ({
      id: measurement.id,
      date: new Date(measurement.timestamp),
      value: metricValue(measurement, path),
    }))
    .filter(point => isNumber(point.value) && Number.isFinite(point.date.getTime()))
    .sort((a, b) => a.date - b.date);
}

export function previousChange(measurements, path) {
  if (measurements.length < 2) return null;
  const current = metricValue(measurements.at(-1), path);
  const previous = metricValue(measurements.at(-2), path);
  return isNumber(current) && isNumber(previous) ? current - previous : null;
}

export function metricStatus(rule, value, codes) {
  if (!rule) return 'unknown';
  const fired = codes.filter(code => rule.triggered_rules?.includes(code));
  if (fired.includes('GATEWAY_UNREACHABLE') || fired.includes('INTERNET_UNREACHABLE')) return 'critical';
  if (!isNumber(value)) return 'unknown';
  return fired.length ? 'warning' : 'good';
}

export function formatNumber(value, unit = '') {
  return isNumber(value)
    ? `${new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 2 }).format(value)}${unit}`
    : '측정 없음';
}

export function formatTime(value) {
  const date = new Date(value);
  return Number.isFinite(date.getTime())
    ? date.toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
    : '시간 없음';
}
