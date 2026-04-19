import { createContext, useState } from 'react';
import { authApi } from '../api/auth';

// Context object — exported so hooks in the same directory can consume it.
// The useAuth hook lives in ./useAuth.js to keep this file
// components-only (satisfies eslint's react-refresh rule).
// eslint-disable-next-line react-refresh/only-export-components
export const AuthContext = createContext(null);


function readStoredUser() {
  const token = localStorage.getItem('access_token');
  if (!token) return null;
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    if (payload.exp * 1000 > Date.now()) {
      return { id: payload.sub, role: payload.role };
    }
    localStorage.clear();
  } catch {
    localStorage.clear();
  }
  return null;
}


export function AuthProvider({ children }) {
  // Lazy initial state reads localStorage synchronously on mount — no
  // useEffect + setState flicker, no cascading re-renders.
  const [user, setUser] = useState(readStoredUser);

  const login = async (email, password) => {
    const { data } = await authApi.login({ email, password });
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    const payload = JSON.parse(atob(data.access_token.split('.')[1]));
    setUser({ id: payload.sub, role: payload.role });
    return data;
  };

  const logout = () => {
    localStorage.clear();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading: false, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
