import React from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import DesktopLayout from './layouts/DesktopLayout';
import MobileLayout from './layouts/MobileLayout';
import { useWindowWidth } from './hooks/useWindowWidth';
import { AppProvider } from './context/AppContext';
import { AuthProvider } from './context/AuthContext';
import ProtectedRoute from './components/Auth/ProtectedRoute';
import { ToastProvider } from './components/ui/Toast';
import LoginPage from './pages/LoginPage';
import SignupPage from './pages/SignupPage';

function Dashboard() {
  const width = useWindowWidth();
  const isDesktop = width >= 1024;

  return (
    <ProtectedRoute>
      <AppProvider>{isDesktop ? <DesktopLayout /> : <MobileLayout />}</AppProvider>
    </ProtectedRoute>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/signup" element={<SignupPage />} />
          <Route path="/" element={<Dashboard />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </ToastProvider>
  );
}
