/**
 * Side-by-side declared-vs-OCR diff for the admin review panel.
 *
 * The reconciliation step compares each field the citizen typed in
 * (declared) against the value the OCR extracted from the uploaded
 * document. Today the admin sees only "match rate: 80%" + a row of
 * mismatch tags — not enough to make a confident manual-review call.
 *
 * This component renders one row per field with the declared value,
 * the OCR-extracted value, and a status pill. Officers can spot at a
 * glance whether a flag is "looks like a typo in the application" vs
 * "the document says something completely different".
 *
 * Input shape comes straight from reconciliation.reconcile() —
 * field_results: { declared_key: { declared, extracted, match,
 * similarity, status } }
 */

const STATUS_COPY = {
  exact_match: { label: 'Exact', color: '#16a34a', icon: '=' },
  close_match: { label: 'Close', color: '#65a30d', icon: '≈' },
  partial_match: { label: 'Partial', color: '#d97706', icon: '~' },
  mismatch: { label: 'Mismatch', color: '#dc2626', icon: '✗' },
  not_found_in_ocr: { label: 'Not found', color: '#6b7280', icon: '?' },
};

const FIELD_LABELS_AR = {
  full_name: 'الاسم الكامل',
  father_name: 'اسم الأب',
  mother_name: 'اسم الأم',
  date_of_birth: 'تاريخ الميلاد',
  place_of_birth: 'مكان الميلاد',
  gender: 'الجنس',
  registry_number: 'رقم السجل',
  registry_place: 'مكان السجل',
  passport_number: 'رقم جواز السفر',
  marital_status: 'الحالة الاجتماعية',
  nationality: 'الجنسية',
};

function rowBackground(status) {
  if (status === 'mismatch') return '#fef2f2';
  if (status === 'partial_match') return '#fffbeb';
  if (status === 'not_found_in_ocr') return '#f9fafb';
  return undefined;
}

export default function ReconciliationDiff({ reconciliation }) {
  if (!reconciliation) return null;

  const fieldResults = reconciliation.field_results || {};
  const entries = Object.entries(fieldResults);
  if (entries.length === 0) return null;

  const integrity = reconciliation.integrity_score;
  const integrityPct = integrity != null ? Math.round(integrity * 100) : null;

  return (
    <div className="recon-diff">
      <div className="recon-diff__summary">
        <span className="recon-diff__title">
          <span className="ar">مقارنة المُدخل مع OCR</span>
          <span className="en"> · Declared vs OCR</span>
        </span>
        {integrityPct != null && (
          <span
            className="recon-diff__score"
            style={{
              color: integrityPct >= 80 ? '#16a34a' : integrityPct >= 50 ? '#d97706' : '#dc2626',
            }}
          >
            {integrityPct}%
          </span>
        )}
      </div>

      <table className="recon-diff__table">
        <thead>
          <tr>
            <th>
              <span className="ar">الحقل</span>
              <span className="en"> · Field</span>
            </th>
            <th>
              <span className="ar">المُدخل</span>
              <span className="en"> · Declared</span>
            </th>
            <th>
              <span className="ar">OCR</span>
            </th>
            <th>
              <span className="ar">الحالة</span>
              <span className="en"> · Status</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([key, result]) => {
            const meta = STATUS_COPY[result.status] || {
              label: result.status,
              color: '#6b7280',
              icon: '·',
            };
            return (
              <tr
                key={key}
                style={{ background: rowBackground(result.status) }}
              >
                <td className="recon-diff__field">
                  <span className="ar">{FIELD_LABELS_AR[key] || key}</span>
                  <span className="en" style={{ display: 'block', fontSize: '0.75rem', color: '#6b7280' }}>
                    {key}
                  </span>
                </td>
                <td className="recon-diff__value">
                  {result.declared != null ? String(result.declared) : <em>—</em>}
                </td>
                <td className="recon-diff__value">
                  {result.extracted != null ? (
                    String(result.extracted)
                  ) : (
                    <em style={{ color: '#9ca3af' }}>not in document</em>
                  )}
                </td>
                <td>
                  <span
                    className="recon-diff__pill"
                    style={{
                      background: `${meta.color}15`,
                      color: meta.color,
                      border: `1px solid ${meta.color}40`,
                    }}
                  >
                    <span style={{ fontFamily: 'monospace' }}>{meta.icon}</span>
                    {' '}
                    {meta.label}
                    {result.similarity != null && result.similarity > 0 && (
                      <small style={{ marginInlineStart: '0.4rem', opacity: 0.7 }}>
                        {Math.round(result.similarity * 100)}%
                      </small>
                    )}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
