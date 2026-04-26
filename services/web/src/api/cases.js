import api from './axios';

export const casesApi = {
  create: (serviceType, declaredFields = {}) =>
    api.post('/cases', { service_type: serviceType, declared_fields: declaredFields }),

  list: () => api.get('/cases'),

  get: (caseId) => api.get(`/cases/${caseId}`),

  getRequiredDocuments: (caseId) => api.get(`/cases/${caseId}/required-documents`),

  getCompleteness: (caseId) => api.get(`/cases/${caseId}/completeness`),

  uploadDocument: (caseId, file, documentType) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('document_type', documentType);
    return api.post(`/cases/${caseId}/documents`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  getDocuments: (caseId) => api.get(`/cases/${caseId}/documents`),

  // Auth-gated URL of an uploaded doc image. Render via <AuthImage src={...} />
  // so the JWT bearer header is attached on the GET.
  getDocumentImageUrl: (caseId, documentId) =>
    `${api.defaults.baseURL}/cases/${caseId}/documents/${documentId}/image`,

  submit: (caseId, declaredFields) =>
    api.post(`/cases/${caseId}/submit`, { declared_fields: declaredFields }),

  getTracking: (caseId) => api.get(`/cases/${caseId}/tracking`),

  trackByTrackingId: (trackingId) => api.get(`/cases/track/${trackingId}`),

  createPayment: (caseId) => api.post('/payments', { case_id: caseId }),
};
