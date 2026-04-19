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

  decide: (caseId, { decision, notes, rejection_reasons }) =>
    api.post(`/mukhtar/cases/${caseId}/decide`, { decision, notes, rejection_reasons }),

  getAvailableMukhtars: (caseId) =>
    api.get(`/mukhtar/cases/${caseId}/available-mukhtars`),

  transfer: (caseId, { target_mukhtar_id, reason }) =>
    api.post(`/mukhtar/cases/${caseId}/transfer`, { target_mukhtar_id, reason }),
};