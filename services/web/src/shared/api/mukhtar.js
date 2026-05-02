import api from './axios';

export const mukhtarApi = {
  getStats: () => api.get('/mukhtar/stats'),

  getCases: ({ status, limit = 50, offset = 0 } = {}) => {
    const params = { limit, offset };
    if (status) params.status = status;
    return api.get('/mukhtar/cases', { params });
  },

  getCaseDetail: (caseId) => api.get(`/mukhtar/cases/${caseId}`),

  getDocumentImageUrl: (caseId, documentId) =>
    `${api.defaults.baseURL}/mukhtar/cases/${caseId}/documents/${documentId}/image`,

  downloadForm: (caseId) =>
    api.get(`/mukhtar/cases/${caseId}/form`, { responseType: 'blob' }),

  // Forward the full payload — backend requires the three attestation
  // booleans (residence/photo/presence) on every "approve" decision and
  // a rejection_reasons array on "reject". Earlier versions destructured
  // only {decision, notes, rejection_reasons} here, which silently dropped
  // the attestations and produced a 400 "Approve requires all three
  // attestations" — i.e. mukhtar approvals were uniformly broken.
  decide: (caseId, body) =>
    api.post(`/mukhtar/cases/${caseId}/decide`, body),

  getAvailableMukhtars: (caseId) =>
    api.get(`/mukhtar/cases/${caseId}/available-mukhtars`),

  transfer: (caseId, { target_mukhtar_id, reason }) =>
    api.post(`/mukhtar/cases/${caseId}/transfer`, { target_mukhtar_id, reason }),
};