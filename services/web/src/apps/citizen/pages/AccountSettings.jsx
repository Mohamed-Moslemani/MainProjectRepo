import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { authApi } from '@shared/api/auth';
import { referenceApi } from '@shared/api/reference';
import { useToast } from '@shared/context/useToast';
import { isLebanesePhone, normalizeLebanesePhone } from '@shared/utils/lebanesePhone';
import flagImg from '@shared/assets/Figure_1.png';
import '@shared/styles/dashboard.css';
import L from '@shared/components/L';

/**
 * Citizen account settings: profile edit + password change.
 *
 * Only the editable subset of the profile is here — phone, address,
 * marital status, place of birth. Identity fields (name, DOB,
 * registry numbers) live behind a formal correction flow we don't
 * implement on the client yet, so we render them read-only.
 */
export default function AccountSettings() {
  const toast = useToast();
  const [me, setMe] = useState(null);
  const [loading, setLoading] = useState(true);

  // Profile form
  const [profileDraft, setProfileDraft] = useState({});
  const [savingProfile, setSavingProfile] = useState(false);

  // Password form
  const [pwd, setPwd] = useState({ current: '', next: '', confirm: '' });
  const [changingPwd, setChangingPwd] = useState(false);

  // Server-driven sect dropdown options.
  const [sects, setSects] = useState([]);

  useEffect(() => {
    let cancelled = false;
    referenceApi
      .sects()
      .then(({ data }) => { if (!cancelled) setSects(data.sects || []); })
      .catch(() => {});
    authApi
      .me()
      .then(({ data }) => {
        if (cancelled) return;
        setMe(data);
        setProfileDraft({
          phone: data.phone || '',
          address: data.address || '',
          marital_status: data.marital_status || '',
          place_of_birth: data.place_of_birth || '',
          religious_sect: data.religious_sect || '',
        });
      })
      .catch(() => toast.error('فشل في تحميل بيانات الحساب'))
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  // toast identity is stable across renders from the provider; safe to omit
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onProfileSubmit = async (e) => {
    e.preventDefault();
    if (profileDraft.phone && !isLebanesePhone(profileDraft.phone)) {
      toast.error('رقم الهاتف غير صالح. استخدم صيغة لبنانية (مثال: +961 70 123 456).');
      return;
    }
    const patch = {
      ...profileDraft,
      phone: profileDraft.phone ? normalizeLebanesePhone(profileDraft.phone) : null,
      // Empty string from the dropdown means "decline to state" — send
      // null so the server clears it instead of failing the validator.
      religious_sect: profileDraft.religious_sect || null,
    };
    setSavingProfile(true);
    try {
      const { data } = await authApi.updateProfile(patch);
      setMe(data);
      toast.success('تم حفظ التعديلات');
    } catch (err) {
      toast.error(err.response?.data?.detail || 'فشل في حفظ التعديلات');
    } finally {
      setSavingProfile(false);
    }
  };

  const onPasswordSubmit = async (e) => {
    e.preventDefault();
    if (!pwd.current || !pwd.next) {
      toast.error('الرجاء إدخال كلمة المرور الحالية والجديدة');
      return;
    }
    if (pwd.next.length < 8) {
      toast.error('كلمة المرور الجديدة يجب أن تكون 8 أحرف على الأقل');
      return;
    }
    if (pwd.next !== pwd.confirm) {
      toast.error('كلمتا المرور غير متطابقتين');
      return;
    }
    if (pwd.next === pwd.current) {
      toast.error('كلمة المرور الجديدة يجب أن تختلف عن الحالية');
      return;
    }
    setChangingPwd(true);
    try {
      await authApi.changePassword(pwd.current, pwd.next);
      toast.success('تم تغيير كلمة المرور. سيتم تسجيل خروج باقي الجلسات.');
      setPwd({ current: '', next: '', confirm: '' });
    } catch (err) {
      toast.error(err.response?.data?.detail || 'فشل في تغيير كلمة المرور');
    } finally {
      setChangingPwd(false);
    }
  };

  if (loading) {
    return (
      <div className="dashboard">
        <main className="dashboard-main"><div className="loading-spinner" /></main>
      </div>
    );
  }
  if (!me) return null;

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <div className="dashboard-header__inner">
          <div className="dashboard-header__brand">
            <img src={flagImg} alt="" className="dashboard-header__flag" />
            <div>
              <h1 className="dashboard-header__title"><L ar="إعدادات الحساب" en="Account settings" /></h1>
            </div>
          </div>
          <div className="dashboard-header__actions">
            <Link to="/dashboard" className="btn btn--outline btn--sm">
              <L ar="العودة للرئيسية" en="· Dashboard" />
            </Link>
          </div>
        </div>
      </header>

      <main className="dashboard-main" style={{ maxWidth: 720 }}>
        {/* Read-only identity */}
        <section className="detail-section">
          <h2>
            <L ar="معلومات الهوية" en="Identity (read-only)" />
          </h2>
          <p style={{ fontSize: '0.85rem', color: '#6b7280' }}>
            <L>{{ ar: <>لا يمكن تعديل هذه الحقول هنا — تستخدم لمطابقة سجل القيد المدني.</>, en: <>These fields can't be edited here — they're matched against the civil registry.</> }}</L>
          </p>
          <dl className="case-detail__dl" style={{ marginTop: '0.75rem' }}>
            <dt>Email</dt><dd>{me.email}{me.email_verified ? ' ✓' : ''}</dd>
            <dt>Full name</dt><dd>{me.full_name}</dd>
            <dt>Date of birth</dt><dd>{me.date_of_birth || '—'}</dd>
            <dt>Registry №</dt><dd>{me.registry_number || '—'}</dd>
            <dt>Registry place</dt><dd>{me.registry_place || '—'}</dd>
          </dl>
        </section>

        {/* Editable profile */}
        <section className="detail-section">
          <h2>
            <L ar="المعلومات القابلة للتعديل" en="Profile" />
          </h2>
          <form onSubmit={onProfileSubmit} className="settings-form">
            <label>
              <L ar="رقم الهاتف" en="· Phone" />
              <input
                type="tel"
                dir="ltr"
                value={profileDraft.phone}
                onChange={(e) => setProfileDraft({ ...profileDraft, phone: e.target.value })}
                placeholder="+961 70 123 456"
              />
            </label>
            <label>
              <L ar="العنوان" en="· Address" />
              <input
                type="text"
                value={profileDraft.address}
                onChange={(e) => setProfileDraft({ ...profileDraft, address: e.target.value })}
              />
            </label>
            <label>
              <L ar="مكان الولادة" en="· Place of birth" />
              <input
                type="text"
                value={profileDraft.place_of_birth}
                onChange={(e) => setProfileDraft({ ...profileDraft, place_of_birth: e.target.value })}
              />
            </label>
            <label>
              <L ar="الحالة الاجتماعية" en="· Marital status" />
              <select
                value={profileDraft.marital_status}
                onChange={(e) => setProfileDraft({ ...profileDraft, marital_status: e.target.value })}
              >
                <option value="">—</option>
                <option value="single">Single</option>
                <option value="married">Married</option>
                <option value="divorced">Divorced</option>
                <option value="widowed">Widowed</option>
              </select>
            </label>
            <label>
              <L ar="المذهب" en="· Religious sect (optional)" />
              <select
                value={profileDraft.religious_sect || ''}
                onChange={(e) => setProfileDraft({ ...profileDraft, religious_sect: e.target.value })}
              >
                <option value="">— (declined to state)</option>
                {sects.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.ar} / {s.en}
                  </option>
                ))}
              </select>
            </label>
            <button type="submit" className="btn btn--primary" disabled={savingProfile}>
              {savingProfile ? 'Saving…' : (
                <>
                  <L ar="حفظ التعديلات" en="· Save" />
                </>
              )}
            </button>
          </form>
        </section>

        {/* Password change */}
        <section className="detail-section">
          <h2>
            <L ar="تغيير كلمة المرور" en="Change password" />
          </h2>
          <form onSubmit={onPasswordSubmit} className="settings-form">
            <label>
              <L ar="كلمة المرور الحالية" en="· Current password" />
              <input
                type="password"
                value={pwd.current}
                onChange={(e) => setPwd({ ...pwd, current: e.target.value })}
                autoComplete="current-password"
              />
            </label>
            <label>
              <L ar="كلمة المرور الجديدة" en="· New password" />
              <input
                type="password"
                value={pwd.next}
                onChange={(e) => setPwd({ ...pwd, next: e.target.value })}
                autoComplete="new-password"
                minLength={8}
              />
            </label>
            <label>
              <L ar="تأكيد كلمة المرور" en="· Confirm new password" />
              <input
                type="password"
                value={pwd.confirm}
                onChange={(e) => setPwd({ ...pwd, confirm: e.target.value })}
                autoComplete="new-password"
                minLength={8}
              />
            </label>
            <button type="submit" className="btn btn--primary" disabled={changingPwd}>
              {changingPwd ? 'Changing…' : (
                <>
                  <L ar="تغيير كلمة المرور" en="· Change" />
                </>
              )}
            </button>
            <p style={{ fontSize: '0.8rem', color: '#6b7280' }}>
              <L>{{ ar: <>سيتم تسجيل خروج كل الأجهزة الأخرى عند تغيير كلمة المرور.</>, en: <>All other sessions will be signed out when you change your password.</> }}</L>
            </p>
          </form>
        </section>
      </main>
    </div>
  );
}
