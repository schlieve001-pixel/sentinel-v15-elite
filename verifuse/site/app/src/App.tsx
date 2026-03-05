import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "./lib/auth";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ToastContainer } from "./components/Toast";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import LeadDetail from "./pages/LeadDetail";
import Admin from "./pages/Admin";
import Pricing from "./pages/Pricing";
import PreSale from "./pages/PreSale";
import "./App.css";

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ToastContainer />
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/preview" element={<ErrorBoundary><Dashboard /></ErrorBoundary>} />
          <Route path="/dashboard" element={<ErrorBoundary><Dashboard /></ErrorBoundary>} />
          <Route path="/lead/:assetId" element={<ErrorBoundary><LeadDetail /></ErrorBoundary>} />
          <Route path="/admin" element={<ErrorBoundary><Admin /></ErrorBoundary>} />
          <Route path="/pricing" element={<ErrorBoundary><Pricing /></ErrorBoundary>} />
          <Route path="/pre-sale" element={<ErrorBoundary><PreSale /></ErrorBoundary>} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
