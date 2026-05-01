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

  // Stripe webhook ledger (admin-only). Used by the replay UI for
  // events whose handler errored after the StripeEvent row was
  // already persisted — Stripe stops retrying once it sees a 200,
  // so without manual replay those side-effects never run.
  listStripeEvents: ({ limit = 50, offset = 0, event_type, case_id } = {}) => {
    const params = { limit, offset };
    if (event_type) params.event_type = event_type;
    if (case_id) params.case_id = case_id;
    return api.get('/admin/stripe-events', { params });
  },
  replayStripeEvent: (eventId) =>
    api.post(`/admin/stripe-events/${encodeURIComponent(eventId)}/replay`),

  // Hard-delete a case + all its dependent rows. Admin role only,
  // audit-logged server-side.
  deleteCase: (caseId) => api.delete(`/admin/cases/${caseId}`),
};