import { formatNumber } from '@/lib/dashboard';
import { statusNames } from '@/lib/presentation';

export default function MetricCard({ label, value, unit = '', change, status = 'unknown', note }) {
  const changeLabel = typeof change === 'number' && Number.isFinite(change)
    ? `${change > 0 ? '↑ +' : change < 0 ? '↓ ' : '→ '}${formatNumber(Math.abs(change), unit)}`
    : '이전 측정과 비교 불가';

  return <div className="kpi-card">
    <div className="kpi-top"><span>{label}</span><span className={`status-dot ${status}`} aria-hidden="true" /></div>
    <strong>{typeof value === 'string' ? value : formatNumber(value, unit)}</strong>
    <div className="kpi-bottom"><span>{note || changeLabel}</span><b className={`status-text ${status}`}>{statusNames[status]}</b></div>
  </div>;
}
