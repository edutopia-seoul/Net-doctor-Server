import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import MetricCard from '@/components/dashboard/MetricCard';
import TimeSeriesPanel from '@/components/dashboard/TimeSeriesPanel';
import DiagnosisPanel from '@/components/dashboard/DiagnosisPanel';
import MeasurementTable from '@/components/dashboard/MeasurementTable';
import { getAgents, getDiagnosis, getDiagnoses, getHistory } from '@/lib/api';
import { formatNumber, formatTime, metricStatus, metricValue, previousChange } from '@/lib/dashboard';
import { collectorText, findingText, ruleName, severityNames } from '@/lib/presentation';
import './tailwind.css';
import './styles.css';

const pages = ['개요', '측정 상세', 'AI 진단', '이력'];
const chartSpecs = [
  { title: '인터넷 RTT', description: '외부 대상 평균 왕복 지연', metric: 'internet_ping.avg_rtt_ms', unit: ' ms', color: '#43baa9' },
  { title: '게이트웨이 RTT', description: '첫 구간 평균 왕복 지연', metric: 'gateway_ping.avg_rtt_ms', unit: ' ms', color: '#78a7f2' },
  { title: '인터넷 패킷 손실률', description: 'Ping 응답의 손실 비율', metric: 'internet_ping.packet_loss_pct', unit: '%', color: '#d6a758', area: true },
  { title: '시스템 DNS 응답', description: '실패·결측은 0으로 표시하지 않음', metric: 'dns.system_ms', unit: ' ms', color: '#aa8ee2' },
  { title: 'HTTP 첫 응답 시간', description: 'TTFB · 네트워크와 서버 요인 포함', metric: 'http.ttfb_ms', unit: ' ms', color: '#e08c7c' },
  { title: 'TCP 재전송률', description: 'TShark 캡처 기준 비율', metric: 'tcp.retransmission_pct', unit: '%', color: '#8db98c' },
];
const metricSpecs = [
  { label: '게이트웨이 RTT', path: 'gateway_ping.avg_rtt_ms', unit: ' ms', codes: ['GATEWAY_UNREACHABLE', 'LOCAL_HIGH_LATENCY'] },
  { label: '인터넷 RTT', path: 'internet_ping.avg_rtt_ms', unit: ' ms', codes: ['INTERNET_UNREACHABLE', 'EXTERNAL_HIGH_LATENCY'] },
  { label: '패킷 손실률', path: 'internet_ping.packet_loss_pct', unit: '%', codes: ['INTERNET_UNREACHABLE', 'EXTERNAL_PACKET_LOSS'] },
  { label: '시스템 DNS', path: 'dns.system_ms', unit: ' ms', codes: ['DNS_DELAY'] },
  { label: 'HTTP TTFB', path: 'http.ttfb_ms', unit: ' ms', codes: ['HTTP_SERVER_RESPONSE_DELAY'] },
  { label: 'TCP 재전송률', path: 'tcp.retransmission_pct', unit: '%', codes: ['TCP_RETRANSMISSION_HIGH'] },
];

function Charts({ measurements }) {
  return <div className="chart-grid">{chartSpecs.map(spec =>
    <TimeSeriesPanel key={spec.metric} measurements={measurements} {...spec} />
  )}</div>;
}

function App() {
  const [key, setKey] = useState(() => sessionStorage.getItem('netdoctor-key') || '');
  const [page, setPage] = useState('개요');
  const [agents, setAgents] = useState([]);
  const [agentId, setAgentId] = useState('');
  const [diagnoses, setDiagnoses] = useState([]);
  const [history, setHistory] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [limit, setLimit] = useState(20);
  const [state, setState] = useState('idle');
  const [error, setError] = useState('');
  const [theme, setTheme] = useState(() => localStorage.getItem('netdoctor-theme') || 'dark');

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    localStorage.setItem('netdoctor-theme', theme);
  }, [theme]);

  async function load(nextKey = key, requestedAgent = agentId) {
    if (!nextKey) return;
    setState('loading');
    setError('');
    try {
      const [agentRows, diagnosisRows] = await Promise.all([getAgents(nextKey), getDiagnoses(nextKey)]);
      const activeId = agentRows.some(agent => agent.agent_id === requestedAgent)
        ? requestedAgent : agentRows[0]?.agent_id || '';
      const measurementRows = activeId ? await getHistory(nextKey, activeId) : [];
      setAgents(agentRows);
      setDiagnoses(diagnosisRows);
      setAgentId(activeId);
      setHistory(measurementRows);
      setSelectedId(current => measurementRows.some(row => row.id === current) ? current : measurementRows.at(-1)?.id ?? null);
      sessionStorage.setItem('netdoctor-key', nextKey);
      setState('ready');
    } catch (cause) {
      setError(cause.message);
      setState('error');
    }
  }

  useEffect(() => { if (key) load(key); }, []);

  async function chooseMeasurement(id) {
    setSelectedId(id);
    setPage('측정 상세');
    if (diagnoses.some(item => item.measurement.id === id)) return;
    try {
      const detail = await getDiagnosis(key, id);
      setDiagnoses(current => [detail, ...current.filter(item => item.measurement.id !== id)]);
    } catch (cause) {
      if (cause.status !== 404) setError(cause.message);
    }
  }

  const diagnosesById = useMemo(
    () => Object.fromEntries(diagnoses.map(item => [item.measurement.id, item])),
    [diagnoses],
  );
  const visibleHistory = history.slice(-limit);
  const latest = history.at(-1);
  const latestDiagnosis = latest && diagnosesById[latest.id];
  const currentRule = latestDiagnosis?.rule_diagnosis;
  const activeAgent = agents.find(agent => agent.agent_id === agentId);
  const selectedMeasurement = history.find(row => row.id === selectedId) || latest;
  const selectedDiagnosis = selectedMeasurement && diagnosesById[selectedMeasurement.id];
  const selectedRule = selectedDiagnosis?.rule_diagnosis;
  const health = !currentRule ? 'unknown' : currentRule.severity === 'normal' ? 'good' : currentRule.severity;
  const recentContact = activeAgent?.last_seen && Date.now() - new Date(activeAgent.last_seen).getTime() < 300000;
  const interfaceName = latest?.network?.default_interface || activeAgent?.metadata?.interfaces?.[0]?.name || '—';

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">N<span>+</span></span><div><strong>NetDoctor</strong><small>NETWORK OBSERVABILITY</small></div></div>
      <p className="side-label">WORKSPACE</p>
      <nav aria-label="대시보드 메뉴">{pages.map((item, index) =>
        <button key={item} className={page === item ? 'active' : ''} aria-current={page === item ? 'page' : undefined} onClick={() => setPage(item)}>
          <span className="nav-index">0{index + 1}</span>{item}
        </button>
      )}</nav>
      <div className="sidebar-bottom"><span className="side-label">데이터 원칙</span><p>실측값 → 규칙 판단 → AI 가설</p><small>추정값을 측정 사실로 표시하지 않습니다.</small></div>
    </aside>

    <main className="workspace">
      <header className="topbar">
        <div><p className="eyebrow">NETDOCTOR / MONITORING</p><h1>네트워크 관측 대시보드</h1><p className="subtitle">실제 Agent 측정부터 규칙 진단과 AI 설명까지 한눈에 확인합니다.</p></div>
        <div className="top-actions">
          <button className="button secondary" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>{theme === 'dark' ? '☀ 밝게' : '☾ 어둡게'}</button>
          <button className="button primary" onClick={() => load()} disabled={!key || state === 'loading'}>↻ 새로고침</button>
        </div>
      </header>

      <div className="control-bar">
        <form className="key-form" onSubmit={event => { event.preventDefault(); load(key); }}>
          <label htmlFor="api-key">API 키</label>
          <input id="api-key" type="password" autoComplete="off" value={key} onChange={event => setKey(event.target.value)} placeholder="연결 키 입력" required />
          <button className="button secondary" type="submit">연결</button>
        </form>
        <label className="select-control">Agent
          <select value={agentId} onChange={event => load(key, event.target.value)} disabled={!agents.length}>
            {!agents.length && <option value="">Agent 없음</option>}
            {agents.map(agent => <option key={agent.agent_id} value={agent.agent_id}>{agent.hostname}</option>)}
          </select>
        </label>
        <label className="select-control">표시 범위
          <select value={limit} onChange={event => setLimit(Number(event.target.value))}>
            {[20, 50, 100].map(value => <option value={value} key={value}>최근 {value}건</option>)}
          </select>
        </label>
      </div>

      {error && <div className="error-banner" role="alert">{error} {history.length > 0 && '현재 보이는 값은 마지막으로 불러온 데이터입니다.'}<button onClick={() => load()}>다시 시도</button></div>}
      {state === 'loading' && <div className="loading-banner" role="status">측정값과 진단을 불러오는 중입니다…</div>}
      {state === 'idle' && <div className="welcome-state">API 키를 입력하고 연결하면 실제 Agent 측정값이 표시됩니다.</div>}
      {state !== 'idle' && !agents.length && state !== 'loading' && <div className="empty-state">등록된 Agent가 없습니다.</div>}

      {activeAgent && <>
        <section className="agent-strip">
          <div><span className="field-label">ACTIVE AGENT</span><strong>{activeAgent.hostname}</strong><small>{interfaceName} · {activeAgent.os}</small></div>
          <div><span className="field-label">마지막 수신</span><strong>{formatTime(activeAgent.last_seen)}</strong><small>별도 heartbeat 없이 마지막 수신 시각으로 표시</small></div>
          <span className={`agent-state ${recentContact ? 'recent' : 'stale'}`}>{recentContact ? '최근 5분 내 수신' : '5분 이상 미수신'}</span>
        </section>

        {page === '개요' && <>
          <div className="section-title"><div><p className="eyebrow">01 / HEALTH SUMMARY</p><h2>마지막 측정의 네트워크 상태</h2></div><span>기준: 최신 측정 {latest ? `#${latest.id}` : '없음'}</span></div>
          <div className="kpi-grid">
            <MetricCard label="종합 상태" value={currentRule ? severityNames[currentRule.severity] || currentRule.severity : '진단 대기'} status={health}
              note={currentRule ? `발동 규칙 ${currentRule.triggered_rules.length}개 · 점수 미생성` : '규칙 결과 없음'} />
            {metricSpecs.map(spec => <MetricCard key={spec.path} label={spec.label} value={metricValue(latest, spec.path)} unit={spec.unit}
              change={previousChange(history, spec.path)} status={metricStatus(currentRule, metricValue(latest, spec.path), spec.codes)} />)}
          </div>
          <div className="section-title"><div><p className="eyebrow">02 / TRENDS</p><h2>네트워크 지표 추이</h2></div><span>시간순 · 최근 {visibleHistory.length}건</span></div>
          <Charts measurements={visibleHistory} />
          <div className="section-title"><div><p className="eyebrow">03 / DIAGNOSIS</p><h2>최신 진단 및 측정</h2></div></div>
          <DiagnosisPanel diagnosis={latestDiagnosis} measurementId={latest?.id} compact />
          <MeasurementTable measurements={visibleHistory} diagnosesById={diagnosesById} selectedId={selectedId} onSelect={chooseMeasurement} />
        </>}

        {page === '측정 상세' && <>
          <div className="section-title"><div><p className="eyebrow">MEASUREMENT DETAIL</p><h2>측정 #{selectedMeasurement?.id ?? '—'}</h2></div><span>{selectedMeasurement ? formatTime(selectedMeasurement.timestamp) : '측정 없음'}</span></div>
          {!selectedMeasurement ? <div className="empty-state">측정 기록이 없습니다.</div> : <>
            <section className="panel detail-intro"><div><span className="field-label">인터페이스</span><strong>{selectedMeasurement.network?.default_interface || '측정 없음'}</strong></div><div><span className="field-label">Gateway</span><strong>{selectedMeasurement.network?.gateway || '측정 없음'}</strong></div><div><span className="field-label">Internet 대상</span><strong>{selectedMeasurement.target_profile?.internet_host || '측정 없음'}</strong></div><div><span className="field-label">HTTP 대상</span><strong>{selectedMeasurement.target_profile?.http_url || '측정 없음'}</strong></div></section>
            <div className="kpi-grid detail-kpis">{metricSpecs.map(spec => <MetricCard key={spec.path} label={spec.label}
              value={metricValue(selectedMeasurement, spec.path)} unit={spec.unit} change={null}
              status={metricStatus(selectedRule, metricValue(selectedMeasurement, spec.path), spec.codes)} note="Agent 실측값" />)}</div>
            <div className="detail-grid">
              <section className="panel"><p className="eyebrow">COLLECTORS</p><h3>수집기 상태</h3>{selectedMeasurement.collector_status?.length
                ? <ul className="collector-list">{selectedMeasurement.collector_status.map((item, index) => <li key={index}>{collectorText(item)}</li>)}</ul>
                : <p className="muted">수집기 상태가 없습니다.</p>}</section>
              <section className="panel"><p className="eyebrow">RULE ENGINE</p><h3>규칙 판단 근거</h3>{selectedRule?.findings?.length
                ? <ul className="evidence-list">{selectedRule.findings.map((item, index) => <li key={index}>{findingText(item)}</li>)}</ul>
                : <p className="muted">{selectedRule ? '발동된 규칙이 없습니다.' : '진단이 아직 생성되지 않았습니다.'}</p>}
                <div className="rule-tags">{selectedRule?.triggered_rules?.map(code => <span key={code}>{ruleName(code)}</span>)}</div></section>
            </div>
            <MeasurementTable measurements={visibleHistory} diagnosesById={diagnosesById} selectedId={selectedId} onSelect={chooseMeasurement} />
          </>}
        </>}

        {page === 'AI 진단' && <>
          <div className="section-title"><div><p className="eyebrow">AI DIAGNOSIS</p><h2>실측 사실과 추론의 구분</h2></div><span>측정 #{selectedMeasurement?.id ?? '—'}</span></div>
          <DiagnosisPanel diagnosis={selectedDiagnosis} measurementId={selectedMeasurement?.id} />
        </>}

        {page === '이력' && <>
          <div className="section-title"><div><p className="eyebrow">HISTORY</p><h2>측정 이력</h2></div><span>시간순 · 최근 {visibleHistory.length}건</span></div>
          <Charts measurements={visibleHistory} />
          <MeasurementTable measurements={visibleHistory} diagnosesById={diagnosesById} selectedId={selectedId} onSelect={chooseMeasurement} />
        </>}
      </>}
      <footer>NetDoctor · 실측 데이터는 Agent에서 수집되며 AI 가설은 측정 사실이 아닙니다.</footer>
    </main>
  </div>;
}

createRoot(document.getElementById('root')).render(<App />);
