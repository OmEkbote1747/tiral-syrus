'use client'

import { useState, useEffect, useRef } from 'react'
import { Send, Loader2, ShieldAlert } from 'lucide-react'
import ConfirmationCard from './ConfirmationCard'
import { streamChat } from '@/lib/api'

interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  streaming?: boolean
  draft?: DraftData | null
  injectionBlocked?: boolean
}

interface DraftData {
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

const SUGGESTIONS = [
  "What's my current portfolio value?",
  "Show me RELIANCE price and my position",
  "Buy 50 shares of INFY at market",
  "Set a stop-loss on TCS below ₹4000",
  "Show today's P&L across all positions",
]

export default function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '0',
      role: 'assistant',
      content: "Good morning. I'm StockItUp, your AI trading copilot. I can read your portfolio, quote live prices, and prepare orders for your approval. What would you like to do?",
    },
  ])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [history, setHistory] = useState<{ role: string; content: string }[]>([])
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef  = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = async (text?: string) => {
    const userText = text || input.trim()
    if (!userText || isStreaming) return

    const userMsg: Message = { id: Date.now().toString(), role: 'user', content: userText }
    const assistantId = (Date.now() + 1).toString()
    const assistantMsg: Message = { id: assistantId, role: 'assistant', content: '', streaming: true }

    setMessages(prev => [...prev, userMsg, assistantMsg])
    setInput('')
    setIsStreaming(true)

    let currentDraft: DraftData | null = null

    try {
      await streamChat(
        userText,
        history,
        {
          onText: (chunk) => {
            setMessages(prev =>
              prev.map(m => m.id === assistantId
                ? { ...m, content: m.content + chunk }
                : m
              )
            )
          },
          onDraft: (draftData) => {
            currentDraft = draftData
          },
          onInjectionBlocked: (reason) => {
            setMessages(prev =>
              prev.map(m => m.id === assistantId
                ? { ...m, streaming: false, injectionBlocked: true, content: `⚠️ Message blocked by injection shield: ${reason}` }
                : m
              )
            )
          },
          onDone: () => {
            setMessages(prev =>
              prev.map(m => m.id === assistantId
                ? { ...m, streaming: false, draft: currentDraft }
                : m
              )
            )
            setHistory(prev => [
              ...prev,
              { role: 'user', content: userText },
              { role: 'assistant', content: assistantMsg.content },
            ])
          },
        }
      )
    } catch (err) {
      setMessages(prev =>
        prev.map(m => m.id === assistantId
          ? { ...m, streaming: false, content: 'Connection error. Please try again.' }
          : m
        )
      )
    } finally {
      setIsStreaming(false)
      inputRef.current?.focus()
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const handleOrderApproved = (orderId: string) => {
    setMessages(prev =>
      prev.map(m =>
        m.draft?.order_id === orderId
          ? { ...m, draft: null }
          : m
      )
    )
  }

  return (
    <div className="flex flex-col h-full">

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((msg) => (
          <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-2xl ${msg.role === 'user' ? 'order-user' : 'order-assistant'}`}>

              {msg.role === 'assistant' && (
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs accent-text font-bold tracking-wider">STOCKITUP</span>
                  {msg.streaming && <Loader2 size={10} className="animate-spin accent-text" />}
                </div>
              )}

              {msg.injectionBlocked ? (
                <div className="flex items-start gap-2 p-3 rounded-lg"
                     style={{ background: '#ff4d6d15', border: '1px solid var(--danger)' }}>
                  <ShieldAlert size={16} style={{ color: 'var(--danger)', marginTop: 2, flexShrink: 0 }} />
                  <span style={{ color: 'var(--danger)', fontSize: 13 }}>{msg.content}</span>
                </div>
              ) : (
                <div
                  className={`px-4 py-3 rounded-xl text-sm ${
                    msg.role === 'user'
                      ? 'ml-auto'
                      : msg.streaming ? 'streaming-text' : ''
                  }`}
                  style={{
                    background: msg.role === 'user' ? 'var(--accent-dim)' : 'var(--surface-2)',
                    border: `1px solid ${msg.role === 'user' ? 'var(--accent)' : 'var(--border)'}`,
                    color: 'var(--text)',
                    whiteSpace: 'pre-wrap',
                    fontFamily: 'var(--font-body)',
                  }}
                >
                  {msg.content}
                </div>
              )}

              {/* Draft confirmation card */}
              {msg.draft && !msg.injectionBlocked && (
                <div className="mt-3">
                  <ConfirmationCard
                    draft={msg.draft}
                    onApproved={() => handleOrderApproved(msg.draft!.order_id)}
                    onRejected={() => handleOrderApproved(msg.draft!.order_id)}
                  />
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Suggestions */}
      {messages.length <= 1 && (
        <div className="px-4 pb-2 flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => sendMessage(s)}
              className="text-xs px-3 py-1.5 rounded-full transition-all hover:opacity-90"
              style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="p-4 border-t" style={{ borderColor: 'var(--border)' }}>
        <div className="flex items-end gap-3 p-3 rounded-xl"
             style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a message… (Enter to send, Shift+Enter for newline)"
            rows={1}
            className="flex-1 resize-none bg-transparent outline-none text-sm"
            style={{ color: 'var(--text)', fontFamily: 'var(--font-body)', maxHeight: 120 }}
            disabled={isStreaming}
          />
          <button
            onClick={() => sendMessage()}
            disabled={!input.trim() || isStreaming}
            className="p-2 rounded-lg transition-all disabled:opacity-30"
            style={{ background: 'var(--accent)', color: '#000' }}
          >
            {isStreaming
              ? <Loader2 size={16} className="animate-spin" />
              : <Send size={16} />
            }
          </button>
        </div>
        <p className="text-xs muted-text mt-2 text-center">
          No trade executes without your explicit approval.
        </p>
      </div>
    </div>
  )
}
