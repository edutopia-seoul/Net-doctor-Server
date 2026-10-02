import { formatNumber, formatTime, metricValue } from '@/lib/dashboard';
import { severityNames } from '@/lib/presentation';

export default function MeasurementTable({ measurements, diagnosesById, selectedId, onSelect }) {
  return <section className="panel table-panel">
    <div className="panel-heading"><div><p className="eyebrow">RECENT MEASUREMENTS</p><h3>최근 측정 목록</h3></div><span className="muted">{measurements.length}건</span></div>
    {!measurements.length ? <div className="empty-state">측정 기록이 없습니다.</div> : <div className="table-scroll">
      <table>
        <thead><tr><th>ID</th><th>측정 시각</th><th>Health Score</th><th>인터넷 RTT</th><th>손실률</th><th>시스템 DNS</th><th>HTTP TTFB</th><th>규칙 진단</th></tr></thead>
        <tbody>{[...measurements].reverse().map(row => {
          const rule = diagnosesById[row.id]?.rule_diagnosis;
          return <tr key={row.id} className={selectedId === row.id ? 'selected' : ''}>
            <td><button className="table-link" onClick={() => onSelect(row.id)}>#{row.id}</button></td>
            <td>{formatTime(row.timestamp)}</td>
            <td>{row.health_score?.overall?.score != null ? `${formatNumber(row.health_score.overall.score)} / 100` : '미계산'}</td>
            <td>{formatNumber(metricValue(row, 'internet_ping.avg_rtt_ms'), ' ms')}</td>
            <td>{formatNumber(metricValue(row, 'internet_ping.packet_loss_pct'), '%')}</td>
            <td>{formatNumber(metricValue(row, 'dns.system_ms'), ' ms')}</td>
            <td>{formatNumber(metricValue(row, 'http.ttfb_ms'), ' ms')}</td>
            <td><span className={`state-badge ${rule?.severity || 'unknown'}`}>{rule ? severityNames[rule.severity] || rule.severity : '진단 대기'}</span></td>
          </tr>;
        })}</tbody>
      </table>
    </div>}
  </section>;
}
