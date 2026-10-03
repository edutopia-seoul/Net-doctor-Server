const apiBase = `${import.meta.env.BASE_URL}api/v1`;

async function request(path, key) {
  const response = await fetch(`${apiBase}${path}`, { headers: { 'X-NetDoctor-Key': key } });
  if (!response.ok) {
    const error = new Error(response.status === 401 ? 'API 키가 올바르지 않습니다.' : `데이터 요청에 실패했습니다 (HTTP ${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

export const getAgents = key => request('/agents', key);
const policyQuery = version => `score_version=${encodeURIComponent(version)}`;
export const getDiagnoses = (key, version = 'health-score-v1.1') => request(`/diagnoses?limit=200&${policyQuery(version)}`, key);
export const getHistory = (key, agentId, version = 'health-score-v1.1') =>
  request(`/agents/${encodeURIComponent(agentId)}/history?limit=100&${policyQuery(version)}`, key);
export const getDiagnosis = (key, id, version = 'health-score-v1.1') => request(`/diagnoses/${id}?${policyQuery(version)}`, key);
