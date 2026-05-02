import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import AuthLayout from '@shared/components/AuthLayout';
import PasswordInput from '@shared/components/PasswordInput';
import { authApi } from '@shared/api/auth';
import {
  GOVERNORATES, DISTRICTS, MUNICIPALITIES,
  getDistrictsForGovernorate, getMunicipalitiesForDistrict, isSingleDistrictGovernorate,
} from '@shared/constants/districts';
import L, { useL } from '@shared/components/L';

function getPasswordStrength(pw) {
  let score = 0;
  if (pw.length >= 8) score++;
  if (/[A-Z]/.test(pw)) score++;
  if (/[a-z]/.test(pw)) score++;
  if (/\d/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  return score;
}

function PasswordStrengthBar({ password }) {
  const strength = getPasswordStrength(password);
  const labels = ['', 'weak', 'weak', 'medium', 'strong', 'strong'];
  const level = labels[strength] || '';

  return (
    <div>
      <div className="password-strength">
        {[1, 2, 3, 4, 5].map((i) => (
          <div
            key={i}
            className={`password-strength__bar ${
              i <= strength ? `password-strength__bar--${level}` : ''
            }`}
          />
        ))}
      </div>
      <p className="password-hint">
        <L ar="٨ أحرف على الأقل، حرف كبير وصغير، رقم، ورمز خاص" en="Min 8 chars, uppercase, lowercase, number, and special character" />
      </p>
    </div>
  );
}

// Strip non-Arabic characters in real-time (keeps Arabic, spaces, hyphens, common punctuation)
const filterArabic = (value) => value.replace(/[^\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF\s\-'.،؛]/g, '');

const ARABIC_ONLY_FIELDS = new Set([
  'first_name', 'last_name', 'father_name', 'mother_name', 'place_of_birth', 'address',
]);

const FIELDS = [
  { name: 'first_name', ar: 'الاسم', en: 'First Name', required: true, type: 'text', placeholder: 'الاسم الأول', arabicOnly: true },
  { name: 'last_name', ar: 'اسم العائلة', en: 'Last Name', required: true, type: 'text', placeholder: 'اسم العائلة', arabicOnly: true },
  { name: 'email', ar: 'البريد الإلكتروني', en: 'Email', required: true, type: 'email', placeholder: 'you@example.com', dir: 'ltr' },
  { name: 'password', ar: 'كلمة المرور', en: 'Password', required: true, type: 'password', placeholder: 'أنشئ كلمة مرور قوية', dir: 'ltr' },
];

const PERSONAL_ROWS = [
  [
    { name: 'father_name', ar: 'اسم الأب', en: "Father's Name", placeholder: 'اسم الأب', arabicOnly: true },
    { name: 'mother_name', ar: 'اسم الأم', en: "Mother's Name", placeholder: 'اسم الأم', arabicOnly: true },
  ],
  [
    { name: 'date_of_birth', ar: 'تاريخ الميلاد', en: 'Date of Birth', type: 'date' },
    { name: 'place_of_birth', ar: 'مكان الميلاد', en: 'Place of Birth', placeholder: 'مثلاً: بيروت', arabicOnly: true },
  ],
  [
    { name: 'gender', ar: 'الجنس', en: 'Gender', type: 'select', options: [
      { value: '', ar: '-- اختر --', en: 'Select' },
      { value: 'male', ar: 'ذكر', en: 'Male' },
      { value: 'female', ar: 'أنثى', en: 'Female' },
    ]},
    { name: 'marital_status', ar: 'الحالة الاجتماعية', en: 'Marital Status', type: 'select', options: [
      { value: '', ar: '-- اختر --', en: 'Select' },
      { value: 'single', ar: 'أعزب/عزباء', en: 'Single' },
      { value: 'married', ar: 'متزوج/ة', en: 'Married' },
      { value: 'divorced', ar: 'مطلق/ة', en: 'Divorced' },
      { value: 'widowed', ar: 'أرمل/ة', en: 'Widowed' },
    ]},
  ],
  [
    { name: 'phone', ar: 'رقم الهاتف', en: 'Phone', type: 'tel', placeholder: '+961 ...', dir: 'ltr' },
    { name: 'address', ar: 'العنوان', en: 'Address', placeholder: 'عنوان السكن', arabicOnly: true },
  ],
];

const initialForm = {
  first_name: '', last_name: '', email: '', password: '',
  father_name: '', mother_name: '',
  date_of_birth: '', place_of_birth: '', gender: '', registry_number: '',
  registry_place: '', municipality: '', phone: '', address: '', marital_status: '',
};

export default function Register() {
  const navigate = useNavigate();
  const { pick } = useL();
  const [form, setForm] = useState(initialForm);
  const [governorate, setGovernorate] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm({ ...form, [name]: ARABIC_ONLY_FIELDS.has(name) ? filterArabic(value) : value });
    setError('');
  };

  const handleGovernorateChange = (e) => {
    const gov = e.target.value;
    setGovernorate(gov);
    // Auto-select district for single-district governorates (Beirut, Akkar)
    if (gov && isSingleDistrictGovernorate(gov)) {
      const autoDistrict = getDistrictsForGovernorate(gov)[0].value;
      setForm({ ...form, registry_place: autoDistrict, municipality: '' });
    } else {
      setForm({ ...form, registry_place: '', municipality: '' });
    }
    setError('');
  };

  const handleDistrictChange = (e) => {
    setForm({ ...form, registry_place: e.target.value, municipality: '' });
    setError('');
  };

  const handleMunicipalityChange = (e) => {
    setForm({ ...form, municipality: e.target.value });
    setError('');
  };

  const availableDistricts = governorate ? getDistrictsForGovernorate(governorate) : [];
  const availableMunicipalities = form.registry_place ? getMunicipalitiesForDistrict(form.registry_place) : [];

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    if (getPasswordStrength(form.password) < 5) {
      setError(pick({
        ar: 'كلمة المرور يجب أن تحتوي على ٨ أحرف على الأقل، حرف كبير وصغير، رقم، ورمز خاص.',
        en: 'Password must be at least 8 characters with upper + lowercase, a digit, and a special character.',
      }));
      setLoading(false);
      return;
    }

    try {
      const { first_name, last_name, ...rest } = form;
      const payload = Object.fromEntries(
        Object.entries(rest).filter(([, v]) => v !== '')
      );
      payload.full_name = `${first_name} ${last_name}`.trim();
      await authApi.register(payload);
      navigate('/verify-email', { state: { email: form.email } });
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (Array.isArray(detail)) {
        setError(detail.map((d) => d.msg).join('. '));
      } else {
        setError(detail || 'فشل التسجيل. يرجى المحاولة مرة أخرى.');
      }
    } finally {
      setLoading(false);
    }
  };

  const renderField = (field, index) => {
    const commonProps = {
      id: field.name,
      name: field.name,
      className: 'form-input',
      value: form[field.name],
      onChange: handleChange,
      ...(field.dir && { dir: field.dir }),
    };

    return (
      <div className="form-group" key={field.name}>
        <label className="form-label" htmlFor={field.name}>
          <L>{{ ar: <>{field.ar} {field.required ? '*' : ''}</>, en: <>{field.en}</> }}</L>
        </label>
        {field.type === 'select' ? (
          <select {...commonProps}>
            {field.options.map((opt) => (
              <option key={opt.value} value={opt.value}>{pick({ ar: opt.ar, en: opt.en })}</option>
            ))}
          </select>
        ) : field.type === 'password' ? (
          <PasswordInput
            {...commonProps}
            placeholder={field.placeholder || ''}
            required={field.required}
          />
        ) : (
          <input
            {...commonProps}
            type={field.type || 'text'}
            placeholder={field.placeholder || ''}
            required={field.required}
            autoFocus={index === 0 && field.required}
          />
        )}
        {field.name === 'password' && form.password && (
          <PasswordStrengthBar password={form.password} />
        )}
        {field.arabicOnly && (
          <p className="field-hint" style={{ fontSize: '0.7rem', color: 'var(--gray-400)', margin: '0.2rem 0 0' }}>
            <L ar="يرجى الكتابة بالعربية فقط" en="Arabic only" />
          </p>
        )}
      </div>
    );
  };

  return (
    <AuthLayout>
      <h2 className="auth-card__heading">
        <L ar="إنشاء حساب جديد" en="Create your account" />
      </h2>
      <p className="auth-card__subheading">
        <L ar="ابدأ بتقديم طلبات المستندات الخاصة بك اليوم" en="Start your document application today" />
      </p>

      {error && <div className="alert alert--error">{error}</div>}

      <form onSubmit={handleSubmit}>
        {FIELDS.map((f, i) => renderField(f, i))}

        <div className="form-section-label">
          <L ar="المعلومات الشخصية" en="Personal Information" />
        </div>

        {PERSONAL_ROWS.map((row, ri) => (
          <div className="form-row" key={ri}>
            {row.map((f) => renderField(f))}
          </div>
        ))}

        {/* Cascading location: Governorate -> District -> Municipality */}
        <div className="form-section-label">
          <L ar="مكان السجل" en="Registry Location" />
        </div>

        <div className="form-row">
          <div className="form-group">
            <label className="form-label" htmlFor="governorate">
              <L ar="المحافظة" en="Governorate" />
            </label>
            <select
              id="governorate"
              name="governorate"
              className="form-input"
              value={governorate}
              onChange={handleGovernorateChange}
            >
              <option value="">{pick({ ar: '-- اختر المحافظة --', en: '-- Select Governorate --' })}</option>
              {GOVERNORATES.map((g) => (
                <option key={g.value} value={g.value}>{pick({ ar: g.ar, en: g.en })}</option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="registry_place">
              <L ar="القضاء" en="District" />
            </label>
            <select
              id="registry_place"
              name="registry_place"
              className="form-input"
              value={form.registry_place}
              onChange={handleDistrictChange}
              disabled={!governorate || isSingleDistrictGovernorate(governorate)}
            >
              {isSingleDistrictGovernorate(governorate) ? (
                availableDistricts.map((d) => (
                  <option key={d.value} value={d.value}>{pick({ ar: d.ar, en: d.en })}</option>
                ))
              ) : (
                <>
                  <option value="">{pick({ ar: '-- اختر القضاء --', en: '-- Select District --' })}</option>
                  {availableDistricts.map((d) => (
                    <option key={d.value} value={d.value}>{pick({ ar: d.ar, en: d.en })}</option>
                  ))}
                </>
              )}
            </select>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="municipality">
              <L ar="البلدة / القرية" en="Municipality" />
            </label>
            <select
              id="municipality"
              name="municipality"
              className="form-input"
              value={form.municipality}
              onChange={handleMunicipalityChange}
              disabled={!form.registry_place}
            >
              <option value="">{pick({ ar: '-- اختر البلدة --', en: '-- Select Municipality --' })}</option>
              {availableMunicipalities.map((m) => (
                <option key={m.value} value={m.value}>{m.en}</option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="registry_number">
              <L ar="رقم السجل" en="Registry Number" />
            </label>
            <input
              id="registry_number"
              name="registry_number"
              className="form-input"
              value={form.registry_number}
              onChange={handleChange}
              placeholder="رقم السجل"
            />
          </div>
        </div>

        <button type="submit" className="btn btn--primary" disabled={loading}>
          {loading ? <span className="spinner" /> : (
            <>
              <L ar="إنشاء الحساب" en="Create Account" />
            </>
          )}
        </button>
      </form>

      <p className="auth-footer">
        <L>{{ ar: <>لديك حساب بالفعل؟ <Link to="/login">سجّل الدخول</Link></>, en: <>Already have an account? <Link to="/login">Sign in</Link></> }}</L>
      </p>
    </AuthLayout>
  );
}
