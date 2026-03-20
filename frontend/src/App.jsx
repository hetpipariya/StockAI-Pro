import { useState, useEffect } from 'react'
import { useAuth } from './context/AuthContext'
import LoginPage from './components/Auth/LoginPage'
import { useTradingEngine } from './hooks/useTradingEngine'
import MobileLayout from './layouts/MobileLayout'
import DesktopLayout from './layouts/DesktopLayout'
import { Routes, Route } from 'react-router-dom'
import NewsPage from './pages/NewsPage/NewsPage'

function Dashboard() {
  const { user, token, loading: authLoading, logout } = useAuth()
  const engine = useTradingEngine()
  const [activeTab, setActiveTab] = useState('chart')

  const [isMobile, setIsMobile] = useState(window.innerWidth < 768)

  useEffect(() => {
    const handleResize = () => setIsMobile(window.innerWidth < 768)
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  if (authLoading) {
    return (
      <div className="flex items-center justify-center h-screen w-screen bg-[#0b0f14]">
        <div className="text-teal-500 font-mono animate-pulse">Initializing Interface...</div>
      </div>
    )
  }

  if (!user || !token) {
    return <LoginPage />
  }

  return isMobile ? (
    <MobileLayout engine={engine} activeTab={activeTab} setActiveTab={setActiveTab} onLogout={logout} />
  ) : (
    <DesktopLayout engine={engine} onLogout={logout} />
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/news" element={<NewsPage />} />
    </Routes>
  )
}
