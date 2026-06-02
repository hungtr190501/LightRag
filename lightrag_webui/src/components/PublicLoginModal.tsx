import { useState, useRef, useEffect } from 'react'
import { loginToServer } from '@/api/lightrag'
import { useAuthStore } from '@/stores/state'
import { XIcon, Loader2Icon, LogInIcon, ZapIcon } from 'lucide-react'

interface Props {
  onClose: () => void
  onSuccess: () => void
}

export default function PublicLoginModal({ onClose, onSuccess }: Props) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const usernameRef = useRef<HTMLInputElement>(null)

  useEffect(() => { usernameRef.current?.focus() }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username.trim() || !password) { setError('Vui lòng nhập đầy đủ tên đăng nhập và mật khẩu'); return }
    setLoading(true); setError('')
    try {
      const response = await loginToServer(username.trim(), password)
      const isGuest = response.auth_mode === 'disabled'
      useAuthStore.getState().login(
        response.access_token,
        isGuest,
        response.core_version,
        response.api_version,
        response.webui_title ?? null,
        response.webui_description ?? null,
      )
      onSuccess()
      onClose()
    } catch {
      setError('Sai tên đăng nhập hoặc mật khẩu')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-200 dark:border-zinc-800">
          <div className="flex items-center gap-2">
            <ZapIcon className="size-4 text-emerald-500" />
            <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Đăng nhập quản trị</span>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400">
            <XIcon className="size-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="px-5 py-5 space-y-4">
          <div>
            <label className="block text-xs font-medium text-zinc-500 dark:text-zinc-400 mb-1.5">
              Tên đăng nhập
            </label>
            <input
              ref={usernameRef}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="admin"
              autoComplete="username"
              className="w-full px-3 py-2 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-sm text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-zinc-500 dark:text-zinc-400 mb-1.5">
              Mật khẩu
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="current-password"
              className="w-full px-3 py-2 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-sm text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>

          {error && (
            <p className="text-xs text-red-500 bg-red-50 dark:bg-red-950/40 px-3 py-2 rounded-lg">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium text-white bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 transition-colors"
          >
            {loading ? <Loader2Icon className="size-4 animate-spin" /> : <LogInIcon className="size-4" />}
            {loading ? 'Đang đăng nhập…' : 'Đăng nhập'}
          </button>
        </form>
      </div>
    </div>
  )
}
