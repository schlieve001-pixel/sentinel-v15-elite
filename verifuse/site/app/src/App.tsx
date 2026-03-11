import { useEffect } from "react";
import { BrowserRouter, Routes, Route, useNavigate, useLocation } from "react-router-dom";
import { AuthProvider } from "./lib/auth";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ToastContainer } from "./components/Toast";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Register from "./pages/Register";
import ForgotPassword from "./pages/ForgotPassword";
import ResetPassword from "./pages/ResetPassword";
import Dashboard from "./pages/Dashboard";
import LeadDetail from "./pages/LeadDetail";
import Admin from "./pages/Admin";
import Pricing from "./pages/Pricing";
import PreSale from "./pages/PreSale";
import Coverage from "./pages/Coverage";
import MyCases from "./pages/MyCases";
import TaxDeed from "./pages/TaxDeed";
import UnclaimedProperty from "./pages/UnclaimedProperty";
import Account from "./pages/Account";
import Terms from "./pages/Terms";
import Privacy from "./pages/Privacy";
import "./App.css";

// Detect admin.verifuse.tech subdomain and auto-redirect to /admin
function AdminSubdomainRedirect() {
  const navigate = useNavigate();
  const location = useLocation();
  useEffect(() => {
    const hostname = window.location.hostname;
    if ((hostname === "admin.verifuse.tech" || hostname.startsWith("admin.")) && location.pathname !== "/admin") {
      navigate("/admin", { replace: true });
    }
  }, [navigate, location.pathname]);
  return null;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AdminSubdomainRedirect />
        <ToastContainer />
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="/preview" element={<ErrorBoundary><Dashboard /></ErrorBoundary>} />
          <Route path="/dashboard" element={<ErrorBoundary><Dashboard /></ErrorBoundary>} />
          <Route path="/lead/:assetId" element={<ErrorBoundary><LeadDetail /></ErrorBoundary>} />
          <Route path="/admin" element={<ErrorBoundary><Admin /></ErrorBoundary>} />
          <Route path="/pricing" element={<ErrorBoundary><Pricing /></ErrorBoundary>} />
          <Route path="/pre-sale" element={<ErrorBoundary><PreSale /></ErrorBoundary>} />
          <Route path="/coverage" element={<ErrorBoundary><Coverage /></ErrorBoundary>} />
          <Route path="/my-cases" element={<ErrorBoundary><MyCases /></ErrorBoundary>} />
          <Route path="/tax-deed" element={<ErrorBoundary><TaxDeed /></ErrorBoundary>} />
          <Route path="/unclaimed" element={<ErrorBoundary><UnclaimedProperty /></ErrorBoundary>} />
          <Route path="/account" element={<ErrorBoundary><Account /></ErrorBoundary>} />
          <Route path="/terms" element={<Terms />} />
          <Route path="/privacy" element={<Privacy />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
