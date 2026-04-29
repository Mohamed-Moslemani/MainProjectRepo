import api from './axios';

// Server-owned reference data (sects, GDGS centres, validity tiers,
// renewal reasons). The gateway is the source of truth — keep these
// out of the React bundle so the policy engine and the UI agree.
export const referenceApi = {
  sects: () => api.get('/reference/sects'),
  centres: () => api.get('/reference/gdgs-centres'),
  passportValidity: () => api.get('/reference/passport-validity'),
  renewalReasons: () => api.get('/reference/renewal-reasons'),
};
