import React, { useEffect, useState } from 'react';
import { BrowserRouter, Navigate, Routes, Route } from 'react-router-dom';
import ErrorBoundary from './components/ErrorBoundary';
import { ToastProvider } from './components/Toast';
import ProtectedRoute from './components/ProtectedRoute';
import { AppInitializer } from './components/AppInitializer';
import Dashboard from './pages/Dashboard';
import Signals from './pages/Signals';
import Trades from './pages/Trades';
import Settings from './pages/Settings';
import Login from './pages/Login';
import ForgotPassword from './pages/ForgotPassword';
import Landing from './pages/Landing';
import DesktopLayout from './layouts/DesktopLayout';

const MOBILE_BREAKPOINT = 768;

function LandingEntry() {
  const [isMobile, setIsMobile] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.innerWidth < MOBILE_BREAKPOINT;
  });

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;

    const mediaQuery = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`);
    const onChange = (event) => setIsMobile(event.matches);

    setIsMobile(mediaQuery.matches);

    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', onChange);
      return () => mediaQuery.removeEventListener('change', onChange);
    }

    mediaQuery.addListener(onChange);
    return () => mediaQuery.removeListener(onChange);
  }, []);

  if (isMobile) {
    return <Navigate to="/login" replace />;
  }

  return <Landing />;
}

export default function App() {
  return (
    <ErrorBoundary>
      <ToastProvider>
        <AppInitializer>
          <BrowserRouter>
            <Routes>
              <Route path="/" element={<LandingEntry />} />
              <Route path="/landing" element={<LandingEntry />} />
              <Route path="/login" element={<Login />} />
              <Route path="/forgot-password" element={<ForgotPassword />} />
              <Route
                path="/dashboard"
                element={
                  <ProtectedRoute>
                    <DesktopLayout>
                      <Dashboard />
                    </DesktopLayout>
                  </ProtectedRoute>
                }
              />
              <Route
                path="/signals"
                element={
                  <ProtectedRoute>
                    <DesktopLayout>
                      <Signals />
                    </DesktopLayout>
                  </ProtectedRoute>
                }
              />
              <Route
                path="/trades"
                element={
                  <ProtectedRoute>
                    <DesktopLayout>
                      <Trades />
                    </DesktopLayout>
                  </ProtectedRoute>
                }
              />
              <Route
                path="/settings"
                element={
                  <ProtectedRoute>
                    <DesktopLayout>
                      <Settings />
                    </DesktopLayout>
                  </ProtectedRoute>
                }
              />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </BrowserRouter>
        </AppInitializer>
      </ToastProvider>
    </ErrorBoundary>
  );
}