import api from './axios';

export const adminApi = {
  getStats: () => api.get('/admin/stats'),

  getCases: ({ status, limit = 50, offset = 0 } = {}) => {
    const params = { limit, offset };
    if (status) params.status = status;
    return api.get('/admin/cases', { params });
  },

  getAuditLogs: ({ case_id, action, limit = 50, offset = 0 } = {}) => {
    const params = { limit, offset };
    if (case_id) params.case_id = case_id;
    if (action) params.action = action;
    return api.get('/admin/audit-logs', { params });
  },

  updateCaseStatus: (caseId, { status, notes, rejection_reasons }) =>
    api.patch(`/cases/${caseId}/status`, { status, notes, rejection_reasons }),

  getCaseDetail: (caseId) => api.get(`/cases/${caseId}`),

  getCaseDocuments: (caseId) => api.get(`/cases/${caseId}/documents`),

  getCaseTracking: (caseId) => api.get(`/cases/${caseId}/tracking`),
};