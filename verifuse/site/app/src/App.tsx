import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "./lib/auth";
import { ErrorBoundary } from "./components/ErrorBoundary";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import LeadDetail from "./pages/LeadDetail";
import "./App.css";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/preview" element={<ErrorBoundary><Dashboard /></ErrorBoundary>} />
          <Route path="/dashboard" element={<ErrorBoundary><Dashboard /></ErrorBoundary>} />
          <Route path="/lead/:assetId" element={<ErrorBoundary><LeadDetail /></ErrorBoundary>} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
