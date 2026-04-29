import { useState } from 'react';
import eyeOn from '@shared/assets/eye-svgrepo-com.svg';
import eyeOff from '@shared/assets/eye-off-outline-svgrepo-com.svg';

export default function PasswordInput({ id, name, value, onChange, placeholder, required, autoFocus }) {
  const [visible, setVisible] = useState(false);

  return (
    <div className="password-wrapper">
      <input
        id={id}
        name={name}
        type={visible ? 'text' : 'password'}
        className="form-input form-input--password"
        placeholder={placeholder}
        value={value}
        onChange={onChange}
        required={required}
        autoFocus={autoFocus}
        dir="ltr"
      />
      <button
        type="button"
        className="password-toggle"
        onClick={() => setVisible(!visible)}
        tabIndex={-1}
        aria-label={visible ? 'Hide password' : 'Show password'}
      >
        <img src={visible ? eyeOff : eyeOn} alt="" className="password-toggle__icon" />
      </button>
    </div>
  );
}
