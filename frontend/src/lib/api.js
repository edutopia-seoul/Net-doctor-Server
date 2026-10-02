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
export const getDiagnoses = key => request('/diagnoses?limit=200', key);
export const getHistory = (key, agentId) =>
  request(`/agents/${encodeURIComponent(agentId)}/history?limit=100`, key);
export const getDiagnosis = (key, id) => request(`/diagnoses/${id}`, key);
