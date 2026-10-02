export const severityNames = { normal: '정상', warning: '주의', critical: '심각' };
export const confidenceNames = { LOW: '낮음', MEDIUM: '보통', HIGH: '높음' };
export const statusNames = { good: '양호', warning: '주의', critical: '심각', unknown: '확인 불가' };

export const ruleNames = {
  GATEWAY_UNREACHABLE: '게이트웨이 연결 불가',
  INTERNET_UNREACHABLE: '인터넷 연결 불가',
  LOCAL_PACKET_LOSS: '게이트웨이 방향 패킷 손실',
  EXTERNAL_PACKET_LOSS: '인터넷 방향 패킷 손실',
  LOCAL_HIGH_LATENCY: '게이트웨이 지연',
  EXTERNAL_HIGH_LATENCY: '인터넷 지연',
  DNS_DELAY: 'DNS 응답 지연',
  TCP_RETRANSMISSION_HIGH: 'TCP 재전송 증가',
  HTTP_SERVER_RESPONSE_DELAY: 'HTTP 첫 응답 지연',
  INSUFFICIENT_DATA: '측정 데이터 부족',
};

const factNames = {
  'gateway_ping.min_rtt_ms': '게이트웨이 최소 RTT',
  'gateway_ping.avg_rtt_ms': '게이트웨이 평균 RTT',
  'gateway_ping.max_rtt_ms': '게이트웨이 최대 RTT',
  'gateway_ping.packet_loss_pct': '게이트웨이 손실률',
  'gateway_ping.jitter_ms': '게이트웨이 지터',
  'internet_ping.min_rtt_ms': '인터넷 최소 RTT',
  'internet_ping.avg_rtt_ms': '인터넷 평균 RTT',
  'internet_ping.max_rtt_ms': '인터넷 최대 RTT',
  'internet_ping.packet_loss_pct': '인터넷 손실률',
  'internet_ping.jitter_ms': '인터넷 지터',
  'dns.system_ms': '시스템 DNS 응답',
  'dns.cloudflare_ms': 'Cloudflare DNS 응답',
  'dns.google_ms': 'Google DNS 응답',
  'dns.resolved_ip': 'DNS 조회 결과 IP',
  'traceroute.hop_count': 'Traceroute Probe 수',
  'traceroute.latency_jump_hop': '지연 증가 지점',
  'traceroute.latency_jump_ms': '지연 증가량',
  'http.dns_ms': 'HTTP DNS 조회',
  'http.connect_ms': 'HTTP 연결',
  'http.tls_ms': 'TLS 연결',
  'http.ttfb_ms': 'HTTP 첫 응답',
  'http.total_ms': 'HTTP 전체',
  'http.status_code': 'HTTP 상태 코드',
  'tcp.captured_packets': 'TCP 캡처 패킷',
  'tcp.retransmissions': 'TCP 재전송 건수',
  'tcp.retransmission_pct': 'TCP 재전송률',
  'tcp.duplicate_ack': 'TCP 중복 ACK',
  'tcp.rst': 'TCP RST',
  'tcp.zero_window': 'TCP Zero Window',
  'throughput.tcp_mbps': 'TCP 처리량',
  'throughput.udp_mbps': 'UDP 처리량',
  'throughput.udp_jitter_ms': 'UDP 지터',
  'throughput.udp_loss_pct': 'UDP 손실률',
};

const findingPrefixes = {
  'gateway packet loss is ': '게이트웨이 손실률 ',
  'internet packet loss is ': '인터넷 손실률 ',
  'gateway average RTT is ': '게이트웨이 평균 RTT ',
  'internet average RTT is ': '인터넷 평균 RTT ',
  'DNS system_ms response is ': '시스템 DNS 응답 ',
  'DNS cloudflare_ms response is ': 'Cloudflare DNS 응답 ',
  'DNS google_ms response is ': 'Google DNS 응답 ',
  'TCP retransmission rate is ': 'TCP 재전송률 ',
  'HTTP TTFB is ': 'HTTP 첫 응답 ',
};

export const ruleName = code => ruleNames[code] || code;
export const factText = value => {
  const separator = value.indexOf('=');
  if (separator < 0) return value;
  const field = value.slice(0, separator);
  return `${factNames[field] || field}: ${value.slice(separator + 1)}`;
};
export const findingText = value => {
  if (value === 'no usable network metrics were supplied') return '분석 가능한 네트워크 측정값이 없습니다.';
  const prefix = Object.keys(findingPrefixes).find(item => value.startsWith(item));
  return prefix ? findingPrefixes[prefix] + value.slice(prefix.length) : value;
};
export const recommendationText = value => value === 'AI analysis unavailable - rule-based diagnosis is still available.'
  ? 'AI 분석을 사용할 수 없습니다. 규칙 기반 진단은 계속 제공됩니다.' : value;
export const collectorText = item =>
  `${item.name}: ${{ ok: '정상', partial: '부분 성공', skipped: '미실행', error: '오류', failed: '실패', unavailable: '사용 불가' }[item.status] || item.status}${item.message ? ` — ${{ 'some resolver queries failed': '일부 DNS 서버 질의 실패', 'not configured': '설정되지 않음' }[item.message] || item.message}` : ''}`;
