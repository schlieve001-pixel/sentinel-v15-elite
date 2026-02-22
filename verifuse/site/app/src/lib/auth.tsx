import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
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
  const navigate = useNavigate();

  const logout = useCallback(() => {
    localStorage.removeItem("vf_token");
    localStorage.removeItem("vf_is_admin");
    localStorage.removeItem("vf_simulate");
    sessionStorage.clear();
    setToken(null);
    setUser(null);
    navigate("/login", { replace: true });
  }, [navigate]);

  const revalidateAuthOrRedirect = useCallback(async () => {
    const storedToken = localStorage.getItem("vf_token");
    if (!storedToken) { logout(); return; }
    try {
      const me = await getMe();
      setUser(me);
    } catch {
      logout();
    }
  }, [logout]);

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

  // BFCache guard: revalidate auth when page is restored from browser cache
  useEffect(() => {
    const handlePageShow = (e: PageTransitionEvent) => {
      if (e.persisted) revalidateAuthOrRedirect();
    };
    window.addEventListener("pageshow", handlePageShow);
    return () => window.removeEventListener("pageshow", handlePageShow);
  }, [revalidateAuthOrRedirect]);

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
