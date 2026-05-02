import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { authApi } from '@shared/api/auth';
import { referenceApi } from '@shared/api/reference';
import { useToast } from '@shared/context/useToast';
import { isLebanesePhone, normalizeLebanesePhone } from '@shared/utils/lebanesePhone';
import flagImg from '@shared/assets/Figure_1.png';
import '@shared/styles/dashboard.css';
import L from '@shared/components/L';
import { useL } from '@shared/hooks/useL';

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
  const { pick } = useL();
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
      .catch(() => toast.error(pick({ ar: 'فشل في تحميل بيانات الحساب', en: 'Failed to load account data' })))
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
      toast.error(pick({
        ar: 'رقم الهاتف غير صالح. استخدم صيغة لبنانية (مثال: +961 70 123 456).',
        en: 'Invalid phone number. Use Lebanese format (e.g. +961 70 123 456).',
      }));
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
      toast.success(pick({ ar: 'تم حفظ التعديلات', en: 'Changes saved' }));
    } catch (err) {
      toast.error(err.response?.data?.detail || pick({ ar: 'فشل في حفظ التعديلات', en: 'Failed to save changes' }));
    } finally {
      setSavingProfile(false);
    }
  };

  const onPasswordSubmit = async (e) => {
    e.preventDefault();
    if (!pwd.current || !pwd.next) {
      toast.error(pick({ ar: 'الرجاء إدخال كلمة المرور الحالية والجديدة', en: 'Please enter both your current and new password' }));
      return;
    }
    if (pwd.next.length < 8) {
      toast.error(pick({ ar: 'كلمة المرور الجديدة يجب أن تكون 8 أحرف على الأقل', en: 'New password must be at least 8 characters' }));
      return;
    }
    if (pwd.next !== pwd.confirm) {
      toast.error(pick({ ar: 'كلمتا المرور غير متطابقتين', en: 'Passwords do not match' }));
      return;
    }
    if (pwd.next === pwd.current) {
      toast.error(pick({ ar: 'كلمة المرور الجديدة يجب أن تختلف عن الحالية', en: 'New password must differ from current' }));
      return;
    }
    setChangingPwd(true);
    try {
      await authApi.changePassword(pwd.current, pwd.next);
      toast.success(pick({
        ar: 'تم تغيير كلمة المرور. سيتم تسجيل خروج باقي الجلسات.',
        en: 'Password changed. Other sessions will be logged out.',
      }));
      setPwd({ current: '', next: '', confirm: '' });
    } catch (err) {
      toast.error(err.response?.data?.detail || pick({ ar: 'فشل في تغيير كلمة المرور', en: 'Failed to change password' }));
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
            <dt><L ar="البريد الإلكتروني" en="Email" /></dt>
            <dd>{me.email}{me.email_verified ? ' ✓' : ''}</dd>
            <dt><L ar="الاسم الكامل" en="Full name" /></dt>
            <dd>{me.full_name}</dd>
            <dt><L ar="تاريخ الولادة" en="Date of birth" /></dt>
            <dd>{me.date_of_birth || '—'}</dd>
            <dt><L ar="رقم السجل" en="Registry №" /></dt>
            <dd>{me.registry_number || '—'}</dd>
            <dt><L ar="محل السجل" en="Registry place" /></dt>
            <dd>{me.registry_place || '—'}</dd>
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
                <option value="single">{pick({ ar: 'أعزب/عزباء', en: 'Single' })}</option>
                <option value="married">{pick({ ar: 'متزوج/ة', en: 'Married' })}</option>
                <option value="divorced">{pick({ ar: 'مطلّق/ة', en: 'Divorced' })}</option>
                <option value="widowed">{pick({ ar: 'أرمل/ة', en: 'Widowed' })}</option>
              </select>
            </label>
            <label>
              <L ar="المذهب" en="· Religious sect (optional)" />
              <select
                value={profileDraft.religious_sect || ''}
                onChange={(e) => setProfileDraft({ ...profileDraft, religious_sect: e.target.value })}
              >
                <option value="">{pick({ ar: '— (يفضّل عدم الإفصاح)', en: '— (declined to state)' })}</option>
                {sects.map((s) => (
                  <option key={s.id} value={s.id}>
                    {pick({ ar: s.ar, en: s.en })}
                  </option>
                ))}
              </select>
            </label>
            <button type="submit" className="btn btn--primary" disabled={savingProfile}>
              {savingProfile ? (
                <L ar="جارٍ الحفظ…" en="Saving…" />
              ) : (
                <L ar="حفظ التعديلات" en="· Save" />
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
              {changingPwd ? (
                <L ar="جارٍ التغيير…" en="Changing…" />
              ) : (
                <L ar="تغيير كلمة المرور" en="· Change" />
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
