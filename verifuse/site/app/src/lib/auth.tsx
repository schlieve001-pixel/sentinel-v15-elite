import { createContext, useContext, useState, useEffect, type ReactNode } from "react";
import { type AuthUser, getMe, login as apiLogin, register as apiRegister, type AuthResponse } from "./api";

interface AuthState {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (data: {
    email: string;
    password: string;
    full_name: string;
    firm_name: string;
    bar_number: string;
  }) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(
    () => localStorage.getItem("vf_token")
  );
  const [loading, setLoading] = useState(!!token);

  useEffect(() => {
    if (!token) return;
    getMe()
      .then(setUser)
      .catch(() => {
        localStorage.removeItem("vf_token");
        setToken(null);
      })
      .finally(() => setLoading(false));
  }, [token]);

  function handleAuth(res: AuthResponse) {
    localStorage.setItem("vf_token", res.token);
    if (res.user.is_admin) {
      localStorage.setItem("vf_is_admin", "1");
    } else {
      localStorage.removeItem("vf_is_admin");
      localStorage.removeItem("vf_simulate");  // Auto-clear for non-admins
    }
    setToken(res.token);
    setUser(res.user);
  }

  async function login(email: string, password: string) {
    const res = await apiLogin(email, password);
    handleAuth(res);
  }

  async function register(data: {
    email: string;
    password: string;
    full_name: string;
    firm_name: string;
    bar_number: string;
  }) {
    const res = await apiRegister(data);
    handleAuth(res);
  }

  function logout() {
    localStorage.removeItem("vf_token");
    localStorage.removeItem("vf_simulate");
    localStorage.removeItem("vf_is_admin");
    setToken(null);
    setUser(null);
    window.location.replace("/login");
  }

  return (
    <AuthContext.Provider value={{ user, token, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
