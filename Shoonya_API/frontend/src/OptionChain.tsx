import { useEffect, useState } from 'react'
import { useMarketWebSocket } from './useMarketWebSocket'
import type { PricesMap, SubscribeToken } from './useMarketWebSocket'

// ── Types ──────────────────────────────────────────────────────────────────────

interface ChainLeg {
  token: string
  tsym: string
  exch: string
  // Initial snapshot from REST (overridden by live WebSocket prices)
  lp?: string
  oi?: string
  v?: string
  h?: string
  l?: string
}

interface ChainRow {
  strike: number
  CE: ChainLeg | null
  PE: ChainLeg | null
}

interface OptionChainData {
  symbol: string
  exchange: string
  expiry: string
  expiries: string[]
  chain: ChainRow[]
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmt(val: string | undefined): string {
  if (!val || val === '-') return '—'
  const n = parseFloat(val)
  if (isNaN(n)) return val
  return n.toLocaleString('en-IN')
}

function extractTokens(data: OptionChainData): SubscribeToken[] {
  return data.chain.flatMap(row => {
    const out: SubscribeToken[] = []
    if (row.CE?.token) out.push({ exch: data.exchange, token: row.CE.token })
    if (row.PE?.token) out.push({ exch: data.exchange, token: row.PE.token })
    return out
  })
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function CeLeg({ leg, prices }: { leg: ChainLeg | null; prices: PricesMap }) {
  if (!leg) {
    return (
      <>
        <td className="py-2 text-right text-gray-700 pr-2">—</td>
        <td className="py-2 text-right text-gray-700 pr-2">—</td>
        <td className="py-2 text-right text-gray-700 font-mono pr-6">—</td>
      </>
    )
  }
  const p = prices[leg.token]
  const lp = p?.lp ?? leg.lp
  const oi = p?.oi ?? leg.oi
  const v  = p?.v  ?? leg.v
  return (
    <>
      <td className="py-2 text-right font-mono text-xs text-gray-500 pr-2">{fmt(oi)}</td>
      <td className="py-2 text-right font-mono text-xs text-gray-500 pr-2">{fmt(v)}</td>
      <td className="py-2 text-right font-mono text-sm font-semibold text-blue-300 pr-6">
        {lp ? lp : '—'}
      </td>
    </>
  )
}

function PeLeg({ leg, prices }: { leg: ChainLeg | null; prices: PricesMap }) {
  if (!leg) {
    return (
      <>
        <td className="py-2 text-left text-gray-700 pl-6">—</td>
        <td className="py-2 text-left text-gray-700 pl-2">—</td>
        <td className="py-2 text-left text-gray-700 pl-2">—</td>
      </>
    )
  }
  const p = prices[leg.token]
  const lp = p?.lp ?? leg.lp
  const oi = p?.oi ?? leg.oi
  const v  = p?.v  ?? leg.v
  return (
    <>
      <td className="py-2 text-left font-mono text-sm font-semibold text-red-300 pl-6">
        {lp ? lp : '—'}
      </td>
      <td className="py-2 text-left font-mono text-xs text-gray-500 pl-2">{fmt(v)}</td>
      <td className="py-2 text-left font-mono text-xs text-gray-500 pl-2">{fmt(oi)}</td>
    </>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

export function OptionChain({ exchanges }: { exchanges: string[] }) {
  const [symbol, setSymbol]       = useState('')
  const [exchange, setExchange]   = useState(exchanges[0] ?? 'MCX')
  const [chainData, setChainData] = useState<OptionChainData | null>(null)
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState<string | null>(null)

  const { prices, subscribe, unsubscribe, wsReady } = useMarketWebSocket()

  // Subscribe to all tokens in the current chain whenever chain or WS readiness changes.
  // The cleanup function unsubscribes — so switching expiry automatically unsubscribes old tokens.
  useEffect(() => {
    if (!chainData || !wsReady) return
    const tokens = extractTokens(chainData)
    subscribe(tokens)
    return () => { unsubscribe(tokens) }
  }, [chainData, wsReady, subscribe, unsubscribe])

  const fetchChain = async (sym: string, exch: string, expiry?: string) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/option-chain', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: sym, exchange: exch, expiry, count: 15 }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || res.statusText)
      }
      const data: OptionChainData = await res.json()
      setChainData(data)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const handleSearch = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!symbol.trim()) return
    fetchChain(symbol.trim().toUpperCase(), exchange)
  }

  const handleExpiryChange = (expiry: string) => {
    if (!chainData) return
    fetchChain(chainData.symbol, chainData.exchange, expiry)
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-5">
      <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">Option Chain</h2>

      {/* Search bar */}
      <form onSubmit={handleSearch} className="flex gap-2">
        <input
          type="text"
          value={symbol}
          onChange={e => setSymbol(e.target.value)}
          placeholder="Symbol (e.g. CRUDEOIL, NIFTY)"
          className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-blue-600 transition-colors"
        />
        <select
          value={exchange}
          onChange={e => setExchange(e.target.value)}
          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-blue-600 transition-colors"
        >
          {exchanges.map(ex => <option key={ex} value={ex}>{ex}</option>)}
        </select>
        <button
          type="submit"
          disabled={loading}
          className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
        >
          {loading ? 'Loading…' : 'Search'}
        </button>
      </form>

      {error && (
        <div className="bg-red-950/60 border border-red-800 text-red-300 text-sm px-4 py-3 rounded-lg">
          {error}
        </div>
      )}

      {chainData && (
        <div className="space-y-4">
          {/* Expiry pills + live indicator — only shown when options exist */}
          {chainData.expiries.length > 0 && <div className="flex items-center gap-3 flex-wrap">
            <span className="text-xs text-gray-500 shrink-0">Expiry</span>
            <div className="flex gap-1.5 flex-wrap">
              {chainData.expiries.map(exp => (
                <button
                  key={exp}
                  onClick={() => handleExpiryChange(exp)}
                  disabled={loading}
                  className={`text-xs px-3 py-1 rounded-full border transition-colors disabled:opacity-50 ${
                    exp === chainData.expiry
                      ? 'bg-blue-600 border-blue-600 text-white'
                      : 'border-gray-700 text-gray-400 hover:border-gray-500 hover:text-gray-200'
                  }`}
                >
                  {exp}
                </button>
              ))}
            </div>
            <span className="ml-auto shrink-0">
              {wsReady ? (
                <span className="flex items-center gap-1.5 text-xs text-emerald-400">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  Live
                </span>
              ) : (
                <span className="text-xs text-gray-600">Connecting…</span>
              )}
            </span>
          </div>}

          {/* Option chain table */}
          {chainData.chain.length === 0 ? (
            <div className="text-center py-10 space-y-2">
              <p className="text-sm text-gray-300">No options found for <span className="font-mono text-white">{chainData.symbol}</span> on <span className="font-mono text-white">{chainData.exchange}</span>.</p>
              <p className="text-xs text-gray-500">Tip: NIFTY / BANKNIFTY options are on <span className="text-blue-400">NFO</span>. Commodities like CRUDEOIL / GOLD are on <span className="text-blue-400">MCX</span>.</p>
            </div>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-gray-800">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr>
                    <th colSpan={3} className="py-2 text-center text-xs font-semibold text-blue-400 border-b border-gray-800 bg-blue-950/20">
                      CALL (CE)
                    </th>
                    <th className="py-2 text-center text-xs font-semibold text-gray-300 border-b border-gray-800 bg-gray-800/50 px-6">
                      STRIKE
                    </th>
                    <th colSpan={3} className="py-2 text-center text-xs font-semibold text-red-400 border-b border-gray-800 bg-red-950/20">
                      PUT (PE)
                    </th>
                  </tr>
                  <tr className="text-xs text-gray-600 border-b border-gray-800/60">
                    <th className="py-1.5 text-right font-medium pr-2">OI</th>
                    <th className="py-1.5 text-right font-medium pr-2">Vol</th>
                    <th className="py-1.5 text-right font-medium pr-6">LTP</th>
                    <th className="py-1.5 text-center font-medium px-6 text-gray-500">―</th>
                    <th className="py-1.5 text-left font-medium pl-6">LTP</th>
                    <th className="py-1.5 text-left font-medium pl-2">Vol</th>
                    <th className="py-1.5 text-left font-medium pl-2">OI</th>
                  </tr>
                </thead>
                <tbody>
                  {chainData.chain.map(row => (
                    <tr
                      key={row.strike}
                      className="border-b border-gray-800/40 hover:bg-gray-800/30 transition-colors"
                    >
                      <CeLeg leg={row.CE} prices={prices} />
                      <td className="py-2 text-center font-mono font-bold text-gray-200 px-6 bg-gray-800/20">
                        {row.strike}
                      </td>
                      <PeLeg leg={row.PE} prices={prices} />
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
