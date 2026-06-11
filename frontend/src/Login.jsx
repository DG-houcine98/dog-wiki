import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { datadogRum } from '@datadog/browser-rum'
import './App.css'

function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [user, setUser] = useState(() => localStorage.getItem('username') || '')
  const navigate = useNavigate()

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!username || !password) return
    setBusy(true)
    setError('')
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok && data.token) {
        localStorage.setItem('auth_token', data.token)
        localStorage.setItem('username', data.user)
        setUser(data.user)
        // Attach the authenticated user to the RUM session so AAP→RUM correlation works
        datadogRum.setUser({ id: data.user, name: data.user })
        setTimeout(() => navigate('/'), 600)
      } else {
        setError(data.error || `Login failed (${res.status})`)
      }
    } catch (err) {
      setError(err.message || 'Network error')
    } finally {
      setBusy(false)
    }
  }

  const handleLogout = () => {
    localStorage.removeItem('auth_token')
    localStorage.removeItem('username')
    setUser('')
    datadogRum.clearUser()
  }

  if (user) {
    return (
      <div className="app">
        <header>
          <div className="header-left">
            <div className="logo-row">
              <img src="/datadog.svg" alt="Datadog" className="dd-logo" />
              <h1>Logged in</h1>
            </div>
            <p className="subtitle">Welcome back, {user}.</p>
          </div>
        </header>
        <form className="add-form" onSubmit={(e) => { e.preventDefault(); handleLogout() }}>
          <h2>Session</h2>
          <p>You are signed in as <strong>{user}</strong>.</p>
          <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1rem' }}>
            <button type="submit">Log out</button>
            <Link to="/" style={{ alignSelf: 'center' }}>Back to dogs</Link>
          </div>
        </form>
      </div>
    )
  }

  return (
    <div className="app">
      <header>
        <div className="header-left">
          <div className="logo-row">
            <img src="/datadog.svg" alt="Datadog" className="dd-logo" />
            <h1>Sign in</h1>
          </div>
          <p className="subtitle">Demo credentials: admin / admin123</p>
        </div>
      </header>

      <form className="add-form" onSubmit={handleSubmit} data-testid="login-form">
        <h2>Account login</h2>
        <div className="form-fields">
          <input
            type="text"
            name="username"
            data-testid="login-username"
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
          />
          <input
            type="password"
            name="password"
            data-testid="login-password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
          <button type="submit" data-testid="login-submit" disabled={busy}>
            {busy ? 'Signing in...' : 'Sign in'}
          </button>
          {error && (
            <div data-testid="login-error" style={{ color: '#c0392b', marginTop: '0.5rem' }}>
              {error}
            </div>
          )}
        </div>
        <p style={{ marginTop: '1rem' }}>
          <Link to="/">← Back to dogs</Link>
        </p>
      </form>
    </div>
  )
}

export default Login
