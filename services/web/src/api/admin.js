import api from './axios';

export const adminApi = {
  getStats: () => api.get('/admin/stats'),

  getCases: ({ status, service_type, search, limit = 50, offset = 0 } = {}) => {
    const params = { limit, offset };
    if (status) params.status = status;
    if (service_type) params.service_type = service_type;
    if (search) params.search = search;
    return api.get('/admin/cases', { params });
  },

  getCaseFull: (caseId) => api.get(`/admin/cases/${caseId}/full`),

  getAuditLogs: ({
    case_id, action, user_id, request_id, since, until,
    limit = 50, offset = 0,
  } = {}) => {
    const params = { limit, offset };
    if (case_id) params.case_id = case_id;
    if (action) params.action = action;
    if (user_id) params.user_id = user_id;
    if (request_id) params.request_id = request_id;
    if (since) params.since = since;
    if (until) params.until = until;
    return api.get('/admin/audit-logs', { params });
  },

  updateCaseStatus: (caseId, { status, notes, rejection_reasons }) =>
    api.patch(`/cases/${caseId}/status`, { status, notes, rejection_reasons }),

  // CSV export of the filtered case list (same filter shape as getCases)
  exportCasesCsv: ({ status, service_type, search } = {}) => {
    const params = {};
    if (status) params.status = status;
    if (service_type) params.service_type = service_type;
    if (search) params.search = search;
    return api.get('/admin/cases.csv', { params, responseType: 'blob' });
  },

  getCaseDetail: (caseId) => api.get(`/cases/${caseId}`),

  getCaseDocuments: (caseId) => api.get(`/cases/${caseId}/documents`),

  getCaseTracking: (caseId) => api.get(`/cases/${caseId}/tracking`),
};