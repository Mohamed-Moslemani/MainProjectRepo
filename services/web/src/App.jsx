import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AuthProvider } from '@shared/context/AuthContext';
import { ToastProvider } from '@shared/context/ToastContext';
import ProtectedRoute from '@shared/components/ProtectedRoute';
import RoleRoute from '@shared/components/RoleRoute';
import ErrorBoundary from '@shared/components/ErrorBoundary';
import IdleLogout from '@shared/components/IdleLogout';
import { ConfirmProvider } from '@shared/components/ConfirmDialog';

import Login from '@shared/pages/auth/Login';
import Register from '@shared/pages/auth/Register';
import VerifyEmail from '@shared/pages/auth/VerifyEmail';
import ForgotPassword from '@shared/pages/auth/ForgotPassword';
import ResetPassword from '@shared/pages/auth/ResetPassword';
import Dashboard from '@citizen/pages/Dashboard';
import CaseDetail from '@citizen/pages/CaseDetail';
import PaymentSuccess from '@citizen/pages/PaymentSuccess';
import PaymentCancelled from '@citizen/pages/PaymentCancelled';
import PublicTrack from '@citizen/pages/PublicTrack';
import AccountSettings from '@citizen/pages/AccountSettings';
import BookAppointment from '@citizen/pages/BookAppointment';
import Help from '@citizen/pages/Help';
import Landing from '@citizen/pages/Landing';

import NotFound from '@shared/pages/NotFound';
import AdminLayout from '@clerk/components/AdminLayout';
import AdminDashboard from '@clerk/pages/AdminDashboard';
import AdminReviewQueue from '@clerk/pages/AdminReviewQueue';
import AdminCases from '@clerk/pages/AdminCases';
import AdminAuditLogs from '@clerk/pages/AdminAuditLogs';
import AdminStripeEvents from '@clerk/pages/AdminStripeEvents';
import AdminUsers from '@clerk/pages/AdminUsers';
import MukhtarLayout from '@mukhtar/components/MukhtarLayout';
import MukhtarDashboard from '@mukhtar/pages/MukhtarDashboard';
import MukhtarCases from '@mukhtar/pages/MukhtarCases';

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <ToastProvider>
        <AuthProvider>
          <ConfirmProvider>
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
            <Route
              path="users"
              element={
                <RoleRoute roles={['admin']}>
                  <AdminUsers />
                </RoleRoute>
              }
            />
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
          </ConfirmProvider>
      </AuthProvider>
        </ToastProvider>
    </BrowserRouter>
    </ErrorBoundary>
  );
}