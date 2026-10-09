'use client'

import { useState, useEffect } from 'react'

export async function streamChat(
  message: string,
  history: { role: string; content: string }[],
  callbacks: {
    onText: (text: string) => void
    onDraft: (draft: any) => void
    onInjectionBlocked: (reason: string) => void
    onDone: () => void
  }
) {
  const res = await fetch('http://localhost:8000/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, conversation_history: history }),
  })

  if (!res.body) throw new Error('No response body')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    const chunk = decoder.decode(value, { stream: true })
    const lines = chunk.split('\n')

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const data = JSON.parse(line.slice(6))
          if (data.type === 'text') {
            callbacks.onText(data.content)
          } else if (data.type === 'draft') {
            callbacks.onDraft(data.data)
          } else if (data.type === 'injection_blocked') {
            callbacks.onInjectionBlocked(data.reason)
          } else if (data.type === 'done') {
            callbacks.onDone()
          }
        } catch (e) {
          // Incomplete JSON chunk, skip
        }
      }
    }
  }
}
