import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import AuthLayout from '../components/AuthLayout';
import { authApi } from '../api/auth';

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
        <span className="ar">٨ أحرف على الأقل، حرف كبير وصغير، رقم، ورمز خاص</span>
        <span className="en">Min 8 chars, uppercase, lowercase, number, and special character</span>
      </p>
    </div>
  );
}

const FIELDS = [
  { name: 'full_name', ar: 'الاسم الكامل', en: 'Full Name', required: true, type: 'text', placeholder: 'أدخل اسمك الكامل' },
  { name: 'email', ar: 'البريد الإلكتروني', en: 'Email', required: true, type: 'email', placeholder: 'you@example.com', dir: 'ltr' },
  { name: 'password', ar: 'كلمة المرور', en: 'Password', required: true, type: 'password', placeholder: 'أنشئ كلمة مرور قوية', dir: 'ltr' },
];

const PERSONAL_ROWS = [
  [
    { name: 'father_name', ar: 'اسم الأب', en: "Father's Name", placeholder: 'اسم الأب' },
    { name: 'mother_name', ar: 'اسم الأم', en: "Mother's Name", placeholder: 'اسم الأم' },
  ],
  [
    { name: 'date_of_birth', ar: 'تاريخ الميلاد', en: 'Date of Birth', type: 'date' },
    { name: 'place_of_birth', ar: 'مكان الميلاد', en: 'Place of Birth', placeholder: 'مثلاً: بيروت' },
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
    { name: 'registry_number', ar: 'رقم السجل', en: 'Registry Number', placeholder: 'رقم السجل' },
    { name: 'registry_place', ar: 'مكان السجل', en: 'Registry Place', placeholder: 'مكان السجل' },
  ],
  [
    { name: 'phone', ar: 'رقم الهاتف', en: 'Phone', type: 'tel', placeholder: '+961 ...', dir: 'ltr' },
    { name: 'address', ar: 'العنوان', en: 'Address', placeholder: 'عنوان السكن' },
  ],
];

const initialForm = {
  email: '', password: '', full_name: '', father_name: '', mother_name: '',
  date_of_birth: '', place_of_birth: '', gender: '', registry_number: '',
  registry_place: '', phone: '', address: '', marital_status: '',
};

export default function Register() {
  const navigate = useNavigate();
  const [form, setForm] = useState(initialForm);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleChange = (e) => {
    setForm({ ...form, [e.target.name]: e.target.value });
    setError('');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    if (getPasswordStrength(form.password) < 5) {
      setError('كلمة المرور يجب أن تحتوي على ٨ أحرف على الأقل، حرف كبير وصغير، رقم، ورمز خاص.');
      setLoading(false);
      return;
    }

    try {
      const payload = Object.fromEntries(
        Object.entries(form).filter(([, v]) => v !== '')
      );
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
          <span className="ar">{field.ar} {field.required ? '*' : ''}</span>
          <span className="en">{field.en}</span>
        </label>
        {field.type === 'select' ? (
          <select {...commonProps}>
            {field.options.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.ar} / {opt.en}</option>
            ))}
          </select>
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
      </div>
    );
  };

  return (
    <AuthLayout>
      <h2 className="auth-card__heading">
        <span className="ar">إنشاء حساب جديد</span>
        <span className="en">Create your account</span>
      </h2>
      <p className="auth-card__subheading">
        <span className="ar">ابدأ بتقديم طلبات المستندات الخاصة بك اليوم</span>
        <span className="en">Start your document application today</span>
      </p>

      {error && <div className="alert alert--error">{error}</div>}

      <form onSubmit={handleSubmit}>
        {FIELDS.map((f, i) => renderField(f, i))}

        <div className="form-section-label">
          <span className="ar">المعلومات الشخصية</span>
          <span className="en">Personal Information</span>
        </div>

        {PERSONAL_ROWS.map((row, ri) => (
          <div className="form-row" key={ri}>
            {row.map((f) => renderField(f))}
          </div>
        ))}

        <button type="submit" className="btn btn--primary" disabled={loading}>
          {loading ? <span className="spinner" /> : (
            <>
              <span className="ar">إنشاء الحساب</span>
              <span className="en">Create Account</span>
            </>
          )}
        </button>
      </form>

      <p className="auth-footer">
        <span className="ar">لديك حساب بالفعل؟ <Link to="/login">سجّل الدخول</Link></span>
        <span className="en">Already have an account? <Link to="/login">Sign in</Link></span>
      </p>
    </AuthLayout>
  );
}
