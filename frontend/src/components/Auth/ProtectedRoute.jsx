/**
 * Protected Route Component
 * Restricts access to authenticated users only.
 * Redirects unauthenticated users to login screen.
 */

import React from 'react';
import { Navigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { useAuthStore } from '@/store/authStore';

/**
 * Protected Route Wrapper
 * @component
 * @param {Object} props - Component props
 * @param {React.ReactNode} props.children - Child components to protect
 */
export function ProtectedRoute({ children }) {
  const { isAuthenticated, isLoading } = useAuthStore();

  // Loading state
  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="text-center"
        >
          <div className="w-12 h-12 border-3 border-blue-400/30 border-t-blue-400 rounded-full animate-spin mx-auto mb-4" />
          <p className="text-slate-400">Initializing...</p>
        </motion.div>
      </div>
    );
  }

  // Redirect to login if not authenticated
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return children;
}

export default ProtectedRoute;
