import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuthStore } from '../store/useAuthStore';

const ProtectedRoute = ({ children }) => {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isLoading = useAuthStore((state) => state.isLoading);
  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;

  if (isLoading) {
    return <div className="text-gray-400 p-8">Checking session...</div>;
  }

  if (!isAuthenticated && !token) {
    return <Navigate to="/login" replace />;
  }

  return children;
};

export default ProtectedRoute;