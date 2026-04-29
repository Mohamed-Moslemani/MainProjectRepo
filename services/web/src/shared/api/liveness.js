import api from './axios';

export const livenessApi = {
  getCredentials: () => api.get('/liveness/credentials'),

  createSession: (caseId) =>
    api.post('/liveness/create-session', { case_id: caseId }),

  getResults: (caseId, sessionId) =>
    api.post('/liveness/get-results', { case_id: caseId, session_id: sessionId }),
};