'use client'

import { useState } from 'react'
import { CheckCircle2, XCircle, Clock, TrendingUp, TrendingDown, AlertTriangle } from 'lucide-react'

interface ConfirmationCardProps {
  draft: {
    order_id: string
    symbol: string
    side: 'BUY' | 'SELL'
    order_type: string
    quantity: number
    price?: number
    quoted_price?: number
    risk_score?: number
    risk_check_passed?: boolean
    risk_reason?: string
  }
  onApproved: () => void
  onRejected: () => void
}

export default function ConfirmationCard({ draft, onApproved, onRejected }: ConfirmationCardProps) {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null)
  const [timeLeft, setTimeLeft] = useState(60)

  // Countdown timer
  useState(() => {
    const timer = setInterval(() => {
      setTimeLeft(prev => {
        if (prev <= 1) {
          clearInterval(timer)
          setResult({ success: false, message: 'Order draft expired. Please request a new quote.' })
          return 0
        }
        return prev - 1
      })
    }, 1000)
    return () => clearInterval(timer)
  })

  const handleApprove = async () => {
    setLoading(true)
    try {
      const res = await fetch('http://localhost:8000/orders/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ order_id: draft.order_id }),
      })
      const data = await res.json()
      setResult({
        success: data.success,
        message: data.success
          ? `Order ${data.status} — ${data.filled_quantity} shares filled at ₹${data.average_price}`
          : `Failed: ${data.message}`,
      })
      if (data.success) onApproved()
    } catch {
      setResult({ success: false, message: 'Network error. Check your connection.' })
    } finally {
      setLoading(false)
    }
  }

  const handleReject = async () => {
    setLoading(true)
    try {
      await fetch('http://localhost:8000/orders/reject', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ order_id: draft.order_id, reason: 'Trader rejected' }),
      })
      setResult({ success: false, message: 'Order draft rejected and discarded.' })
      onRejected()
    } catch {
      setResult({ success: false, message: 'Failed to reject. Try again.' })
    } finally {
      setLoading(false)
    }
  }

  const orderValue = draft.quantity * (draft.quoted_price || draft.price || 0)
  const riskScore = draft.risk_score ?? 80
  const riskColor = riskScore >= 80 ? 'var(--success)' : riskScore >= 50 ? 'var(--warning)' : 'var(--danger)'

  if (result) {
    return (
      <div
        className="confirm-card p-4 flex items-start gap-3"
        style={{
          borderColor: result.success ? 'var(--success)' : 'var(--danger)',
          boxShadow: result.success ? '0 0 20px #00ff8833' : '0 0 20px #ff4d6d33',
        }}
      >
        {result.success ? <CheckCircle2 size={20} style={{ color: 'var(--success)' }} /> : <XCircle size={20} style={{ color: 'var(--danger)' }} />}
        <div className="flex-1">
          <p className="text-sm" style={{ color: result.success ? 'var(--success)' : 'var(--danger)' }}>
            {result.message}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="confirm-card p-5 space-y-4">

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-base font-bold accent-text tracking-wide">{draft.side} {draft.symbol}</h3>
          <p className="text-xs muted-text mt-0.5">{draft.order_type} ORDER</p>
        </div>
        <div className="flex items-center gap-1.5 text-xs"
             style={{ color: timeLeft < 10 ? 'var(--danger)' : 'var(--warning)' }}>
          <Clock size={12} />
          {timeLeft}s
        </div>
      </div>

      {/* Details grid */}
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <span className="muted-text text-xs">Quantity</span>
          <p className="font-mono font-bold mt-0.5">{draft.quantity} shares</p>
        </div>
        <div>
          <span className="muted-text text-xs">Price</span>
          <p className="font-mono font-bold mt-0.5">
            {draft.order_type === 'MARKET' ? 'MARKET' : `₹${draft.price?.toFixed(2)}`}
          </p>
        </div>
        <div>
          <span className="muted-text text-xs">Quoted at</span>
          <p className="font-mono font-bold mt-0.5">₹{draft.quoted_price?.toFixed(2)}</p>
        </div>
        <div>
          <span className="muted-text text-xs">Est. Value</span>
          <p className="font-mono font-bold mt-0.5">₹{orderValue.toLocaleString('en-IN')}</p>
        </div>
      </div>

      {/* Risk score bar */}
      <div>
        <div className="flex items-center justify-between text-xs mb-1">
          <span className="muted-text">Risk Score</span>
          <span className="font-bold" style={{ color: riskColor }}>{riskScore}/100</span>
        </div>
        <div className="h-1.5 rounded-full" style={{ background: 'var(--surface-2)' }}>
          <div className="risk-bar-fill rounded-full" style={{ width: `${riskScore}%`, background: riskColor }} />
        </div>
        {draft.risk_reason && (
          <div className="flex items-start gap-1.5 mt-2 p-2 rounded" style={{ background: '#fbbf2415' }}>
            <AlertTriangle size={12} style={{ color: 'var(--warning)', marginTop: 2 }} />
            <span className="text-xs" style={{ color: 'var(--warning)' }}>{draft.risk_reason}</span>
          </div>
        )}
      </div>

      {/* Action buttons */}
      <div className="flex gap-3 pt-2">
        <button
          onClick={handleApprove}
          disabled={loading || timeLeft === 0}
          className="flex-1 py-2.5 rounded-lg font-semibold text-sm transition-all disabled:opacity-30 accent-glow"
          style={{ background: 'var(--accent)', color: '#000' }}
        >
          {loading ? 'Executing...' : 'Approve & Execute'}
        </button>
        <button
          onClick={handleReject}
          disabled={loading}
          className="px-6 py-2.5 rounded-lg font-semibold text-sm transition-all"
          style={{ border: '1px solid var(--border)', color: 'var(--text-muted)' }}
        >
          Reject
        </button>
      </div>

      <p className="text-xs text-center muted-text">
        This order will only execute if you click Approve within {timeLeft} seconds.
      </p>
    </div>
  )
}
