import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { ToastProvider } from './context/ToastContext';
import ProtectedRoute from './components/ProtectedRoute';
import RoleRoute from './components/RoleRoute';
import ErrorBoundary from './components/ErrorBoundary';
import IdleLogout from './components/IdleLogout';

import Login from './pages/Login';
import Register from './pages/Register';
import VerifyEmail from './pages/VerifyEmail';
import ForgotPassword from './pages/ForgotPassword';
import ResetPassword from './pages/ResetPassword';
import Dashboard from './pages/Dashboard';
import CaseDetail from './pages/CaseDetail';
import PaymentSuccess from './pages/PaymentSuccess';
import PaymentCancelled from './pages/PaymentCancelled';
import PublicTrack from './pages/PublicTrack';
import AccountSettings from './pages/AccountSettings';
import BookAppointment from './pages/BookAppointment';
import Help from './pages/Help';
import Landing from './pages/Landing';

import NotFound from './pages/NotFound';
import AdminLayout from './components/AdminLayout';
import AdminDashboard from './pages/admin/AdminDashboard';
import AdminReviewQueue from './pages/admin/AdminReviewQueue';
import AdminCases from './pages/admin/AdminCases';
import AdminAuditLogs from './pages/admin/AdminAuditLogs';
import AdminStripeEvents from './pages/admin/AdminStripeEvents';
import MukhtarLayout from './components/MukhtarLayout';
import MukhtarDashboard from './pages/mukhtar/MukhtarDashboard';
import MukhtarCases from './pages/mukhtar/MukhtarCases';

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <ToastProvider>
        <AuthProvider>
          <IdleLogout />
          <Routes>
            {/* Public — no auth required */}
            <Route path="/" element={<Landing />} />
            <Route path="/track" element={<PublicTrack />} />
            <Route path="/track/:trackingId" element={<PublicTrack />} />
            <Route path="/help" element={<Help />} />
            <Route path="/terms" element={<Help />} />
            <Route path="/privacy" element={<Help />} />

          {/* Auth */}
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/verify-email" element={<VerifyEmail />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password" element={<ResetPassword />} />

          {/* Citizen dashboard */}
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <Dashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/case/:caseId"
            element={
              <ProtectedRoute>
                <CaseDetail />
              </ProtectedRoute>
            }
          />
          <Route
            path="/account"
            element={
              <ProtectedRoute>
                <AccountSettings />
              </ProtectedRoute>
            }
          />
          <Route
            path="/case/:caseId/appointment"
            element={
              <ProtectedRoute>
                <BookAppointment />
              </ProtectedRoute>
            }
          />

          {/* Stripe return routes — both live behind auth so the polling
              call to /cases/:id has the token already. */}
          <Route
            path="/payment/success"
            element={
              <ProtectedRoute>
                <PaymentSuccess />
              </ProtectedRoute>
            }
          />
          <Route
            path="/payment/cancelled"
            element={
              <ProtectedRoute>
                <PaymentCancelled />
              </ProtectedRoute>
            }
          />

          {/* Admin panel */}
          <Route
            path="/admin"
            element={
              <RoleRoute roles={['admin', 'clerk']}>
                <AdminLayout />
              </RoleRoute>
            }
          >
            <Route index element={<AdminDashboard />} />
            <Route path="review" element={<AdminReviewQueue />} />
            <Route path="cases" element={<AdminCases />} />
            <Route path="audit-logs" element={<AdminAuditLogs />} />
            <Route path="stripe-events" element={<AdminStripeEvents />} />
          </Route>

          {/* Mukhtar panel */}
          <Route
            path="/mukhtar"
            element={
              <RoleRoute roles={['mukhtar']}>
                <MukhtarLayout />
              </RoleRoute>
            }
          >
            <Route index element={<MukhtarDashboard />} />
            <Route path="cases" element={<MukhtarCases />} />
          </Route>

          <Route path="*" element={<NotFound />} />
        </Routes>
      </AuthProvider>
        </ToastProvider>
    </BrowserRouter>
    </ErrorBoundary>
  );
}