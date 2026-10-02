import { confidenceNames, factText, findingText, recommendationText, ruleName, severityNames } from '@/lib/presentation';

function EvidenceList({ items, render = value => value, empty = '표시할 항목이 없습니다.' }) {
  return items?.length
    ? <ul className="evidence-list">{items.map((item, index) => <li key={index}>{render(item)}</li>)}</ul>
    : <p className="muted">{empty}</p>;
}

export default function DiagnosisPanel({ diagnosis, measurementId, compact = false }) {
  const rule = diagnosis?.rule_diagnosis;
  const ai = diagnosis?.ai_diagnosis;
  return <section className="panel diagnosis-panel">
    <div className="panel-heading">
      <div><p className="eyebrow">RULE → AI</p><h3>AI 네트워크 진단</h3><p className="muted">{measurementId ? `측정 #${measurementId}` : '측정 선택 전'}</p></div>
      <span className={`state-badge ${rule?.severity || 'unknown'}`}>{rule ? severityNames[rule.severity] || rule.severity : '진단 대기'}</span>
    </div>
    {!diagnosis && <div className="empty-state">아직 진단 결과가 없습니다. 측정이 처리 중이거나 등록되지 않았습니다.</div>}
    {diagnosis && <>
      <div className="diagnosis-summary">
        <div><span className="field-label">관측된 문제 · 규칙 기반</span><strong>{ai?.available ? ai.primary_cause : rule?.triggered_rules?.map(ruleName).join(', ') || '규칙 진단 결과를 확인하세요.'}</strong></div>
        <div><span className="field-label">AI 신뢰도</span><strong>{ai?.available ? confidenceNames[ai.confidence] || ai.confidence || '—' : '분석 불가'}</strong></div>
      </div>
      {!ai?.available && <div className="notice">AI 분석을 사용할 수 없습니다. 규칙 기반 진단은 계속 제공됩니다.</div>}
      <div className="evidence-grid">
        <div className="evidence-block measured"><h4>실측 사실</h4><EvidenceList items={compact ? ai?.measured_facts?.slice(0, 6) : ai?.measured_facts} render={factText} />{compact && ai?.measured_facts?.length > 6 && <p className="muted">외 {ai.measured_facts.length - 6}개 사실은 AI 진단 탭에서 확인</p>}</div>
        <div className="evidence-block rule"><h4>규칙 판단 근거</h4><EvidenceList items={rule?.findings} render={findingText} empty="발동된 규칙이 없습니다." /></div>
        <div className="evidence-block hypothesis"><h4>가능한 원인 · AI 가설</h4><EvidenceList items={ai?.available ? ai.hypotheses : []} /></div>
        <div className="evidence-block recommendation"><h4>권장 조치 · AI 제안</h4><EvidenceList items={ai?.recommendations} render={recommendationText} /></div>
      </div>
      {!compact && ai?.available && <div className="diagnosis-extra">
        <div><span className="field-label">예상 영향</span><p>{ai.impact || '제공된 측정값만으로 판단하기 어렵습니다.'}</p></div>
        <div><span className="field-label">추가 확인</span><EvidenceList items={ai.additional_checks} /></div>
      </div>}
      {compact && <p className="muted panel-note">AI의 가능성·권고는 실측 사실과 구분해 해석하세요. 전체 가설과 영향은 AI 진단 탭에서 확인할 수 있습니다.</p>}
    </>}
  </section>;
}
