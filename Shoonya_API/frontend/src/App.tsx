import { useState, useEffect, useCallback } from 'react'
import { OptionChain } from './OptionChain'

interface Product {
  prd: string
  s_prdt_ali: string
  exch: string[]
}

interface UserInfo {
  uid: string
  actid: string
  email: string
  m_num: string
  brkname: string
  brnchid: string
  uprev: string
  exarr: string[]
  orarr: string[]
  prarr: Product[]
  request_time: string
}

type AuthMethod = 'rest' | 'playwright' | 'none'

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, options)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || res.statusText)
  }
  return res.json()
}

function Badge({ label, variant = 'default' }: { label: string; variant?: 'default' | 'blue' | 'green' }) {
  const colors = {
    default: 'bg-gray-800 text-gray-300 border-gray-700',
    blue: 'bg-blue-950 text-blue-300 border-blue-800',
    green: 'bg-emerald-950 text-emerald-300 border-emerald-800',
  }
  return (
    <span className={`inline-block text-xs px-2 py-0.5 rounded border font-mono ${colors[variant]}`}>
      {label}
    </span>
  )
}

function SkeletonLine({ width }: { width: number }) {
  return <div className="h-3 bg-gray-800 rounded animate-pulse" style={{ width }} />
}

export default function App() {
  const [connected, setConnected] = useState<boolean | null>(null)
  const [authMethod, setAuthMethod] = useState<AuthMethod>('none')
  const [connecting, setConnecting] = useState(false)
  const [user, setUser] = useState<UserInfo | null>(null)
  const [loadingData, setLoadingData] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadData = useCallback(async () => {
    setLoadingData(true)
    try {
      const u = await apiFetch<UserInfo>('/user')
      setUser(u)
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoadingData(false)
    }
  }, [])

  useEffect(() => {
    apiFetch<{ connected: boolean; method: AuthMethod }>('/status')
      .then(({ connected: c, method }) => {
        setConnected(c)
        setAuthMethod(method)
        if (c) loadData()
      })
      .catch(() => setConnected(false))
  }, [loadData])

  const handleConnect = async () => {
    setConnecting(true)
    setError(null)
    try {
      const res = await apiFetch<{ connected: boolean; method: AuthMethod }>('/connect', { method: 'POST' })
      setConnected(true)
      setAuthMethod(res.method)
      await loadData()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setConnecting(false)
    }
  }

  const handleDisconnect = async () => {
    await apiFetch('/disconnect', { method: 'POST' }).catch(() => {})
    setConnected(false)
    setAuthMethod('none')
    setUser(null)
  }

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center font-bold text-sm select-none">
              G
            </div>
            <span className="font-semibold tracking-tight">Gateway Dashboard</span>
          </div>

          <div className="flex items-center gap-4">
            {connected === null ? (
              <span className="text-sm text-gray-500">Checking connection…</span>
            ) : connected ? (
              <>
                <span className="flex items-center gap-2 text-sm text-emerald-400">
                  <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                  Connected to Shoonya
                </span>
                <span className="text-xs px-2 py-0.5 rounded-full border border-gray-700 text-gray-500">
                  {authMethod === 'playwright' ? 'via OAuth' : 'via REST'}
                </span>
                <button
                  onClick={handleDisconnect}
                  className="text-xs px-3 py-1.5 rounded border border-gray-700 text-gray-400 hover:border-gray-500 hover:text-gray-200 transition-colors cursor-pointer"
                >
                  Disconnect
                </button>
              </>
            ) : (
              <>
                <span className="flex items-center gap-2 text-sm text-red-400">
                  <span className="w-2 h-2 rounded-full bg-red-400" />
                  Disconnected
                </span>
                {connecting && (
                  <span className="text-xs text-gray-500">may take up to 30s</span>
                )}
                <button
                  onClick={handleConnect}
                  disabled={connecting}
                  className="text-xs px-4 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium transition-colors cursor-pointer"
                >
                  {connecting ? 'Connecting…' : 'Connect'}
                </button>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-8 space-y-6">
        {error && (
          <div className="bg-red-950/60 border border-red-800 text-red-300 text-sm px-4 py-3 rounded-lg">
            {error}
          </div>
        )}

        {connected === false && (
          <div className="flex flex-col items-center justify-center py-24 text-center space-y-3">
            <div className="w-16 h-16 rounded-full border-2 border-gray-800 flex items-center justify-center mb-2">
              <svg className="w-8 h-8 text-gray-700" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.19 8.688a4.5 4.5 0 0 1 1.242 7.244l-4.5 4.5a4.5 4.5 0 0 1-6.364-6.364l1.757-1.757m13.35-.622 1.757-1.757a4.5 4.5 0 0 0-6.364-6.364l-4.5 4.5a4.5 4.5 0 0 0 1.242 7.244" />
              </svg>
            </div>
            <p className="text-lg font-medium text-gray-400">Not connected to Shoonya broker</p>
            <p className="text-sm text-gray-600 max-w-sm">
              Click <span className="text-blue-400">Connect</span> above to authenticate using credentials from your <code className="text-gray-500">.env</code> file.
            </p>
          </div>
        )}

        {connected && (
          <div className="space-y-6">
            <OptionChain exchanges={user?.exarr ?? ['MCX', 'NFO', 'NSE', 'BSE', 'CDS']} />

            {/* User Profile card */}
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-5">
              <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">User Profile</h2>

              {loadingData && !user ? (
                <div className="space-y-4">
                  <div className="flex items-center gap-3">
                    <div className="w-12 h-12 rounded-full bg-gray-800 animate-pulse shrink-0" />
                    <div className="space-y-2">
                      <SkeletonLine width={120} />
                      <SkeletonLine width={80} />
                    </div>
                  </div>
                  {[100, 140, 90, 110].map((w, i) => (
                    <div key={i} className="flex justify-between">
                      <SkeletonLine width={60} />
                      <SkeletonLine width={w} />
                    </div>
                  ))}
                </div>
              ) : user ? (
                <>
                  {/* Identity */}
                  <div className="flex items-center gap-4">
                    <div className="w-12 h-12 rounded-full bg-blue-700 flex items-center justify-center text-xl font-bold select-none shrink-0">
                      {user.uid.charAt(0).toUpperCase()}
                    </div>
                    <div>
                      <div className="font-semibold text-white text-lg">{user.uid}</div>
                      <div className="text-xs text-gray-500">Account: {user.actid}</div>
                    </div>
                    <span className="ml-auto text-xs px-2 py-1 rounded-full bg-emerald-950 border border-emerald-800 text-emerald-300">
                      {user.uprev}
                    </span>
                  </div>

                  {/* Contact & broker details */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 pt-1">
                    <InfoRow label="Email" value={user.email} />
                    <InfoRow label="Mobile" value={user.m_num} />
                    <InfoRow label="Broker" value={user.brkname} />
                    <InfoRow label="Branch" value={user.brnchid} />
                  </div>

                  {/* Enabled exchanges */}
                  {user.exarr.length > 0 && (
                    <div className="space-y-1.5 pt-1 border-t border-gray-800">
                      <span className="text-xs text-gray-500">Enabled Exchanges</span>
                      <div className="flex flex-wrap gap-1.5">
                        {user.exarr.map(ex => <Badge key={ex} label={ex} variant="green" />)}
                      </div>
                    </div>
                  )}

                  {/* Order types */}
                  {user.orarr.length > 0 && (
                    <div className="space-y-1.5 border-t border-gray-800 pt-3">
                      <span className="text-xs text-gray-500">Allowed Order Types</span>
                      <div className="flex flex-wrap gap-1.5">
                        {user.orarr.map(o => <Badge key={o} label={o} variant="blue" />)}
                      </div>
                    </div>
                  )}

                  {/* Products */}
                  {user.prarr.length > 0 && (
                    <div className="space-y-2 border-t border-gray-800 pt-3">
                      <span className="text-xs text-gray-500">Enabled Products</span>
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-left text-xs text-gray-600 border-b border-gray-800">
                            <th className="pb-2 pr-4 font-medium">Code</th>
                            <th className="pb-2 pr-4 font-medium">Name</th>
                            <th className="pb-2 font-medium">Exchanges</th>
                          </tr>
                        </thead>
                        <tbody>
                          {user.prarr.map(p => (
                            <tr key={p.prd} className="border-b border-gray-800/40">
                              <td className="py-2 pr-4 font-mono text-gray-300">{p.prd}</td>
                              <td className="py-2 pr-4 text-gray-400">{p.s_prdt_ali}</td>
                              <td className="py-2">
                                <div className="flex flex-wrap gap-1">
                                  {p.exch.map(ex => <Badge key={ex} label={ex} variant="default" />)}
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {user.request_time && (
                    <p className="text-xs text-gray-700 text-right">Last updated: {user.request_time}</p>
                  )}
                </>
              ) : null}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-gray-500">{label}</span>
      <span className="text-gray-200">{value || '—'}</span>
    </div>
  )
}
