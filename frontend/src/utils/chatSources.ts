import type { ChatMessage, SourceReference } from '@/types'

export interface ActiveAssistantSources {
  messageId: string | null
  sources: SourceReference[]
}

export function latestAssistantSources(
  messages: readonly ChatMessage[],
): ActiveAssistantSources {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (message?.role === 'assistant') {
      return { messageId: message.id, sources: message.sources }
    }
  }
  return { messageId: null, sources: [] }
}
