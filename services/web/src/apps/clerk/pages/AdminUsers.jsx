import { useState, useEffect, useCallback } from 'react';
import { adminApi } from '@shared/api/admin';
import L from '@shared/components/L';
import { useL } from '@shared/hooks/useL';
import { useAuth } from '@shared/context/useAuth';

const ROLES = [
  { value: 'citizen', ar: 'مواطن', en: 'Citizen' },
  { value: 'clerk',   ar: 'موظف',  en: 'Clerk' },
  { value: 'mukhtar', ar: 'مختار', en: 'Mukhtar' },
  { value: 'admin',   ar: 'مسؤول', en: 'Admin' },
];

const ROLE_LABEL = Object.fromEntries(ROLES.map((r) => [r.value, r]));

// Minimal Lebanese governorates list — same source as admin.py.
// Mukhtars are routed by registry_place match; this nudges admins
// to pick a value that actually corresponds to real cases.
const REGISTRY_PLACES = [
  'Beirut', 'Mount Lebanon', 'North Lebanon', 'Akkar',
  'South Lebanon', 'Nabatieh', 'Beqaa', 'Baalbek-Hermel',
];

const PAGE_SIZE = 30;

export default function AdminUsers() {
  const { pick } = useL();
  const { user: me } = useAuth();

  const [users, setUsers] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [roleFilter, setRoleFilter] = useState('');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Modal state — null when closed, {mode: 'create'|'edit', user: {...}}
  // when open. The shape matches the form payload one-to-one.
  const [modal, setModal] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const { data } = await adminApi.listUsers({
        role: roleFilter || undefined,
        q: search || undefined,
        limit: PAGE_SIZE,
        offset,
      });
      setUsers(data.users || []);
      setTotal(data.total || 0);
    } catch (err) {
      setError(err.response?.data?.detail || pick({ ar: 'فشل في تحميل المستخدمين', en: 'Failed to load users' }));
    } finally {
      setLoading(false);
    }
  }, [roleFilter, search, offset, pick]);

  useEffect(() => { load(); }, [load]);

  // ── Derived UI ────────────────────────────────────────────────
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div className="admin-page">
      <header className="admin-page__header">
        <h1>
          <L ar="إدارة الموظفين" en="Staff Management" />
        </h1>
        <button
          className="btn btn--primary"
          onClick={() => setModal({
            mode: 'create',
            user: { email: '', password: '', full_name: '', role: 'clerk', registry_place: '', municipality: '', phone: '' },
          })}
        >
          <L ar="إضافة مستخدم" en="Add user" />
        </button>
      </header>

      {/* Filters */}
      <div className="admin-page__filters" style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <select
          value={roleFilter}
          onChange={(e) => { setRoleFilter(e.target.value); setOffset(0); }}
        >
          <option value="">{pick({ ar: 'كل الأدوار', en: 'All roles' })}</option>
          {ROLES.map((r) => (
            <option key={r.value} value={r.value}>{pick({ ar: r.ar, en: r.en })}</option>
          ))}
        </select>
        <input
          type="search"
          placeholder={pick({ ar: 'بحث بالبريد أو الاسم', en: 'Search email or name' })}
          value={search}
          onChange={(e) => { setSearch(e.target.value); setOffset(0); }}
          style={{ flex: '1 1 240px' }}
        />
      </div>

      {error && <div className="alert alert--error" style={{ marginBottom: 12 }}>{error}</div>}

      {/* User table */}
      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th><L ar="البريد" en="Email" /></th>
              <th><L ar="الاسم" en="Name" /></th>
              <th><L ar="الدور" en="Role" /></th>
              <th><L ar="منطقة السجل" en="Registry Place" /></th>
              <th><L ar="البلدية" en="Municipality" /></th>
              <th><L ar="مُتحقَّق" en="Verified" /></th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={7}><L ar="جاري التحميل..." en="Loading..." /></td></tr>
            )}
            {!loading && users.length === 0 && (
              <tr><td colSpan={7}><L ar="لا يوجد مستخدمون" en="No users found" /></td></tr>
            )}
            {!loading && users.map((u) => {
              const r = ROLE_LABEL[u.role] || { ar: u.role, en: u.role };
              return (
                <tr key={u.id}>
                  <td>{u.email}</td>
                  <td>{u.full_name}</td>
                  <td>
                    <span className={`role-badge role-badge--${u.role}`}>
                      {pick({ ar: r.ar, en: r.en })}
                    </span>
                  </td>
                  <td>{u.registry_place || '—'}</td>
                  <td>{u.municipality || '—'}</td>
                  <td>{u.email_verified ? '✓' : '—'}</td>
                  <td>
                    <button
                      className="btn btn--sm btn--outline"
                      onClick={() => setModal({
                        mode: 'edit',
                        user: { ...u, password: '' },
                      })}
                    >
                      <L ar="تعديل" en="Edit" />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="admin-pagination" style={{ marginTop: 16, display: 'flex', gap: 8, alignItems: 'center' }}>
          <button className="btn btn--sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
            <L ar="السابق" en="Prev" />
          </button>
          <span>{currentPage} / {totalPages}</span>
          <button className="btn btn--sm" disabled={currentPage >= totalPages} onClick={() => setOffset(offset + PAGE_SIZE)}>
            <L ar="التالي" en="Next" />
          </button>
        </div>
      )}

      {modal && (
        <UserFormModal
          mode={modal.mode}
          initialUser={modal.user}
          isSelf={modal.mode === 'edit' && modal.user.id === me?.id}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); load(); }}
        />
      )}
    </div>
  );
}


function UserFormModal({ mode, initialUser, isSelf, onClose, onSaved }) {
  const { pick } = useL();
  const [form, setForm] = useState(initialUser);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const isEdit = mode === 'edit';
  const needsLocation = form.role === 'mukhtar';

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async () => {
    setError('');
    if (!isEdit) {
      // Front-end validation; backend re-validates regardless.
      if (!form.email.includes('@')) { setError(pick({ ar: 'بريد غير صالح', en: 'Invalid email' })); return; }
      if ((form.password || '').length < 8) { setError(pick({ ar: 'كلمة المرور 8 أحرف فأكثر', en: 'Password must be 8+ characters' })); return; }
      if (!form.full_name.trim()) { setError(pick({ ar: 'الاسم الكامل مطلوب', en: 'Full name required' })); return; }
    }
    if (needsLocation && (!form.registry_place || !form.municipality)) {
      setError(pick({ ar: 'المختار يحتاج إلى منطقة السجل والبلدية', en: 'Mukhtar requires registry_place + municipality' }));
      return;
    }

    setSubmitting(true);
    try {
      if (isEdit) {
        const payload = {
          role: form.role,
          full_name: form.full_name,
          registry_place: form.registry_place || '',
          municipality: form.municipality || '',
          phone: form.phone || '',
        };
        await adminApi.updateUser(initialUser.id, payload);
      } else {
        await adminApi.createUser({
          email: form.email,
          password: form.password,
          full_name: form.full_name,
          role: form.role,
          registry_place: form.registry_place || '',
          municipality: form.municipality || '',
          phone: form.phone || '',
        });
      }
      onSaved();
    } catch (err) {
      setError(err.response?.data?.detail || pick({ ar: 'فشل الحفظ', en: 'Save failed' }));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h2>
          {isEdit
            ? <L ar="تعديل المستخدم" en="Edit user" />
            : <L ar="إضافة مستخدم" en="Add user" />}
        </h2>

        {error && <div className="alert alert--error">{error}</div>}

        <div className="form-group">
          <label><L ar="البريد الإلكتروني" en="Email" /></label>
          <input
            type="email"
            value={form.email}
            disabled={isEdit}
            onChange={set('email')}
            required
          />
        </div>

        {!isEdit && (
          <div className="form-group">
            <label><L ar="كلمة المرور" en="Password" /></label>
            <input
              type="password"
              value={form.password}
              onChange={set('password')}
              minLength={8}
              required
            />
            <small><L ar="8 أحرف على الأقل" en="At least 8 characters" /></small>
          </div>
        )}

        <div className="form-group">
          <label><L ar="الاسم الكامل" en="Full name" /></label>
          <input type="text" value={form.full_name} onChange={set('full_name')} required />
        </div>

        <div className="form-group">
          <label><L ar="الدور" en="Role" /></label>
          <select value={form.role} onChange={set('role')} disabled={isSelf}>
            {ROLES.map((r) => (
              <option key={r.value} value={r.value}>{pick({ ar: r.ar, en: r.en })}</option>
            ))}
          </select>
          {isSelf && (
            <small style={{ color: '#dc2626' }}>
              <L ar="لا يمكنك تغيير دورك الخاص" en="You can't change your own role" />
            </small>
          )}
        </div>

        {(needsLocation || form.registry_place) && (
          <div className="form-group">
            <label>
              <L ar="منطقة السجل" en="Registry place" />{needsLocation && ' *'}
            </label>
            <select value={form.registry_place || ''} onChange={set('registry_place')} required={needsLocation}>
              <option value="">{pick({ ar: '-- اختر --', en: '-- Select --' })}</option>
              {REGISTRY_PLACES.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
        )}

        {(needsLocation || form.municipality) && (
          <div className="form-group">
            <label>
              <L ar="البلدية" en="Municipality" />{needsLocation && ' *'}
            </label>
            <input
              type="text"
              value={form.municipality || ''}
              onChange={set('municipality')}
              placeholder={pick({ ar: 'مثل: بيروت المركزية', en: 'e.g. Beirut Central' })}
              required={needsLocation}
            />
          </div>
        )}

        <div className="form-group">
          <label><L ar="الهاتف" en="Phone" /></label>
          <input type="tel" value={form.phone || ''} onChange={set('phone')} />
        </div>

        <div className="modal-actions" style={{ display: 'flex', gap: 12, marginTop: 20 }}>
          <button className="btn btn--outline" onClick={onClose} disabled={submitting}>
            <L ar="إلغاء" en="Cancel" />
          </button>
          <button className="btn btn--primary" onClick={submit} disabled={submitting}>
            {submitting
              ? <L ar="جاري الحفظ..." en="Saving..." />
              : <L ar="حفظ" en="Save" />}
          </button>
        </div>
      </div>
    </div>
  );
}
