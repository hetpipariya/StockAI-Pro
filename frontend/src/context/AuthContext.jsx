import { createContext, useContext, useState, useEffect } from 'react'

const AuthContext = createContext(null)

const _rawAuth = import.meta.env.VITE_API_URL || "";
const _cleanAuth = _rawAuth.replace(/\/$/, "");
const API_URL = _cleanAuth ? `${_cleanAuth}/api/v1/auth` : "/api/v1/auth";

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(localStorage.getItem('token'))
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (token) {
      localStorage.setItem('token', token)
      fetchUser()
    } else {
      localStorage.removeItem('token')
      setUser(null)
      setLoading(false)
    }
  }, [token])

  const fetchUser = async () => {
    try {
      const res = await fetch(`${API_URL}/me`, {
        headers: { Authorization: `Bearer ${token}` }
      })
      if (res.ok) {
        setUser(await res.json())
      } else {
        setToken(null)
      }
    } catch {
      setToken(null)
    } finally {
      setLoading(false)
    }
  }

  const login = async (username, password) => {
    const formData = new URLSearchParams()
    formData.append('username', username)
    formData.append('password', password)

    const res = await fetch(`${API_URL}/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: formData
    })
    
    if (!res.ok) throw new Error('Invalid credentials')
    const data = await res.json()
    setToken(data.access_token)
  }

  const signup = async (username, password) => {
    const res = await fetch(`${API_URL}/signup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    })
    
    if (!res.ok) {
      const err = await res.json()
      throw new Error(err.detail || 'Signup failed')
    }
    // Auto login after signup
    return login(username, password)
  }

  const logout = () => setToken(null)

  return (
    <AuthContext.Provider value={{ user, token, loading, login, signup, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
