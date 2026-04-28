import api from './axios';

// Biometric-appointment booking. The flow:
//   1. Citizen lists centres
//   2. Picks a centre, lists open slots for the next ~14 days
//   3. POSTs an appointment for their case + chosen slot
//   4. Officer at the centre confirms (admin endpoint) on arrival
export const appointmentsApi = {
  centres: () => api.get('/appointments/centres'),
  slots: (centreId) => api.get(`/appointments/centres/${centreId}/slots`),
  book: ({ caseId, centreId, slotStart }) =>
    api.post('/appointments', {
      case_id: caseId,
      centre_id: centreId,
      slot_start: slotStart,
    }),
  forCase: (caseId) => api.get(`/cases/${caseId}/appointment`),
};
