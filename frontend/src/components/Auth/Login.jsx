/**
 * Single-User Login Component
 * Minimalist, sleek login screen for admin-only access.
 * No signup, password recovery, or multi-user support.
 */

import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Lock, AlertCircle, Zap } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/store/authStore';

/**
 * Login Component
 * @component
 */
export function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [focusedField, setFocusedField] = useState(null)

  const { login, isLoading, error, clearError, isAuthenticated } = useAuthStore()

  /**
   * Redirect to dashboard if already authenticated
   */
  useEffect(() => {
    if (isAuthenticated) {
      navigate('/dashboard', { replace: true })
    }
  }, [isAuthenticated, navigate])

  /**
   * Handle form submission
   */
  const handleSubmit = async (e) => {
    e.preventDefault()
    clearError()

    if (!email.trim() || !password) {
      return
    }

    const result = await login(email.trim().toLowerCase(), password)
    if (result.success) {
      // Navigation handled by useEffect watching isAuthenticated
      navigate('/dashboard', { replace: true })
    } else {
      console.error('Login failed:', result.error)
    }
  }

  // Clear error on input change
  useEffect(() => {
    if (error) clearError()
  }, [email, password, clearError, error])

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center px-4 relative overflow-hidden">
      {/* Animated background */}
      <div className="absolute inset-0 opacity-40">
        <div className="absolute inset-0 bg-gradient-to-br from-blue-900/20 via-transparent to-purple-900/20" />
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-96 h-96 bg-blue-500/10 rounded-full blur-3xl" />
      </div>

      {/* Login Card */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        className="relative z-10 w-full max-w-md"
      >
        <div className="backdrop-blur-md bg-slate-900/80 border border-blue-500/20 rounded-2xl px-8 py-12 shadow-2xl">
          {/* Logo / Header */}
          <div className="text-center mb-8">
            <div className="flex items-center justify-center gap-2 mb-4">
              <div className="w-10 h-10 bg-gradient-to-br from-blue-400 to-cyan-400 rounded-lg flex items-center justify-center">
                <Zap size={24} className="text-slate-950" />
              </div>
              <h1 className="text-2xl font-bold text-white">
                Stock<span className="text-blue-400">AI</span>
              </h1>
            </div>
            <p className="text-slate-400 text-sm">
              Premium Trading Terminal - Admin Access Only
            </p>
          </div>

          {/* Error Alert */}
          {error && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              className="mb-6 p-3 rounded-lg bg-red-900/20 border border-red-500/30 flex gap-3"
            >
              <AlertCircle size={18} className="text-red-400 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-red-200">{error}</p>
            </motion.div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-5">
            {/* Email Field */}
            <div>
              <label className="block text-xs uppercase tracking-wider text-slate-400 mb-2">
                Email
              </label>
              <motion.input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onFocus={() => setFocusedField('email')}
                onBlur={() => setFocusedField(null)}
                placeholder="admin@example.com"
                className={`w-full px-4 py-3 rounded-lg bg-slate-800/50 border transition-all outline-none ${
                  focusedField === 'email'
                    ? 'border-blue-400 shadow-lg shadow-blue-500/20'
                    : 'border-slate-700 hover:border-slate-600'
                } text-white placeholder-slate-500`}
                whileFocus={{ scale: 1.02 }}
                disabled={isLoading}
              />
            </div>

            {/* Password Field */}
            <div>
              <label className="block text-xs uppercase tracking-wider text-slate-400 mb-2">
                Password
              </label>
              <div className="relative">
                <motion.input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onFocus={() => setFocusedField('password')}
                  onBlur={() => setFocusedField(null)}
                  placeholder="••••••••"
                  className={`w-full px-4 py-3 rounded-lg bg-slate-800/50 border transition-all outline-none pr-12 ${
                    focusedField === 'password'
                      ? 'border-blue-400 shadow-lg shadow-blue-500/20'
                      : 'border-slate-700 hover:border-slate-600'
                  } text-white placeholder-slate-500`}
                  whileFocus={{ scale: 1.02 }}
                  disabled={isLoading}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
                >
                  {showPassword ? '👁️' : '👁️‍🗨️'}
                </button>
              </div>
            </div>

            {/* Submit Button */}
            <motion.button
              type="submit"
              disabled={isLoading || !email || !password}
              className="w-full mt-8 px-4 py-3 rounded-lg font-semibold text-white uppercase tracking-wider transition-all disabled:opacity-50 disabled:cursor-not-allowed bg-gradient-to-r from-blue-500 to-cyan-500 hover:from-blue-600 hover:to-cyan-600 shadow-lg hover:shadow-blue-500/50"
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
            >
              {isLoading ? (
                <span className="flex items-center justify-center gap-2">
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Authenticating...
                </span>
              ) : (
                <span className="flex items-center justify-center gap-2">
                  <Lock size={18} />
                  Sign In
                </span>
              )}
            </motion.button>
          </form>


        </div>
      </motion.div>
    </div>
  )
}

export default Login
