import { useState } from 'react';
import { formatNumber, isNumber } from '@/lib/dashboard';
import { metricName, severityNames } from '@/lib/presentation';

const names = { local: '로컬 네트워크', internet: '인터넷', dns: 'DNS', tcp: 'TCP', http: 'HTTP' };
const qualityNames = { complete: '측정 범위 충족', partial: '부분 측정', unavailable: '계산 불가' };
const label = score => isNumber(score) ? formatNumber(score) : '계산 불가';

export default function HealthScorePanel({ measurement }) {
  const [selected, setSelected] = useState(null);
  const health = measurement?.health_score;
  if (!health) return <section className="panel health-panel"><h3>Network Health Score</h3><p className="muted">이 측정의 점수가 아직 계산되지 않았습니다. 기존 측정값과 규칙 진단은 계속 확인할 수 있습니다.</p></section>;
  const overall = health.overall;
  const active = selected || health.top_causes[0]?.category || 'local';
  const category = health.categories[active];

  return <section className="panel health-panel" aria-label="네트워크 점수와 감점 근거">
    <div className="panel-heading"><div><p className="eyebrow">MEASUREMENT → SCORE → EVIDENCE</p><h3>Network Health Score</h3><p className="muted">측정 #{measurement.id} · 설정 기준으로 계산한 품질 점수</p></div><span className="score-version">{health.score_version}</span></div>
    <div className="health-overall">
      <div className={`overall-number ${overall.severity}`}><strong>{label(overall.score)}</strong>{overall.available && <span>/ 100</span>}</div>
      <div className="overall-description"><span className={`state-badge ${overall.severity}`}>{severityNames[overall.severity] || '확인 불가'} · {overall.severity.toUpperCase()}</span><p>측정 범위 {formatNumber(overall.coverage * 100, '%')} · {qualityNames[overall.quality]}</p>{overall.notes.map((note, index) => <small key={index}>{note}</small>)}<small>AI가 생성한 점수가 아닌 NetDoctor 내부 평가 지표입니다.</small></div>
    </div>
    <div className="category-score-grid">
      {Object.keys(names).map(name => { const item = health.categories[name]; return <button key={name} className={`category-score ${active === name ? 'active' : ''}`} aria-pressed={active === name} onClick={() => setSelected(name)}>
        <span>{names[name]}</span><strong>{label(item.score)}{item.available && <small> / 100</small>}</strong>
        {item.available && <progress max="100" value={item.score} aria-label={`${names[name]} 점수`} />}
        <span className={`status-text ${item.severity === 'normal' ? 'good' : item.severity}`}>{severityNames[item.severity] || '확인 불가'} · {qualityNames[item.quality]}</span>
        <small>측정 범위 {formatNumber(item.coverage * 100, '%')}{item.low_sample ? ' · 작은 TCP 표본' : ''}</small>
      </button>; })}
    </div>
    <div className="score-trace-grid">
      <div className="score-causes"><h4>전체 점수 감소의 주요 근거</h4>{health.top_causes.length ? <ul>{health.top_causes.slice(0, 5).map((cause, index) => <li key={index}><button onClick={() => setSelected(cause.category)}><span>{names[cause.category]} · {metricName(cause.metric)}<small>실측 {formatNumber(cause.value, ` ${cause.unit}`)} · 영역 감점 −{cause.points}</small></span><b>−{formatNumber(cause.weighted_points)}<small>전체 반영 점수</small></b></button></li>)}</ul> : <p className="muted">{overall.available ? '유효한 측정값에서 감점 조건이 확인되지 않았습니다.' : '전체 점수를 계산할 근거가 부족합니다.'}</p>}<p className="score-formula">전체 점수는 계산 가능한 영역 점수의 가중 평균입니다. 측정 범위와 함께 해석하세요.</p></div>
      <div className="score-breakdown"><h4>{names[active]}: 왜 {label(category.score)}{category.available ? '점' : ''}인가?</h4>
        {category.available && <p className="score-equation">100 − {category.deductions.reduce((sum, item) => sum + item.points, 0)} = {label(category.score)}</p>}
        {category.deductions.length ? <ul className="deduction-list">{category.deductions.map(item => <li key={item.metric}><b>−{item.points}</b><div><strong>{metricName(item.metric)} · {formatNumber(item.value, ` ${item.unit}`)}</strong><small>기준 {item.operator === 'gt' ? '>' : '≥'} {formatNumber(item.threshold, ` ${item.unit}`)}{item.assessed_points !== item.points ? ` · 평가 감점 ${item.assessed_points}, 0점 하한 적용` : ''}</small><code>{item.metric}</code></div></li>)}</ul> : <p className="muted">{category.available ? '수집된 지표에서 감점 조건이 없습니다.' : '유효한 성능 지표가 없어 100점으로 대체하지 않습니다.'}</p>}
        {category.notes.map((note, index) => <p className="score-note" key={index}>{note}</p>)}
        <details className="score-evidence"><summary>실측 근거 · 가중치 {formatNumber(health.weights[active] * 100, '%')}</summary><dl>{Object.entries(category.evidence).map(([metric, value]) => <div key={metric}><dt>{metricName(metric)}</dt><dd>{formatNumber(value, metric.endsWith('_ms') ? ' ms' : metric.endsWith('_pct') ? '%' : '')}</dd></div>)}</dl>{category.missing_metrics.length > 0 && <p>미수집/유효하지 않음: {category.missing_metrics.map(metricName).join(', ')}</p>}</details>
      </div>
    </div>
  </section>;
}
