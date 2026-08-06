import {
  BASE_TIME,
  defaultSettings,
  evaluationFixtures,
  fileFixtures,
  indexFixtures,
  knowledgeBaseFixtures,
  messageFixtures,
  sessionFixtures,
} from '@/mocks/fixtures'
import type {
  ChatMessage,
  ChatSession,
  EvaluationTask,
  FileRecord,
  IndexCollection,
  KnowledgeBase,
  AppSettings,
} from '@/types'

export interface MockDatabase {
  knowledgeBases: KnowledgeBase[]
  files: FileRecord[]
  sessions: ChatSession[]
  messages: Record<string, ChatMessage[]>
  indexes: IndexCollection[]
  evaluations: EvaluationTask[]
  settings: AppSettings
  sequence: number
}

function createDatabase(): MockDatabase {
  return {
    knowledgeBases: structuredClone(knowledgeBaseFixtures),
    files: structuredClone(fileFixtures),
    sessions: structuredClone(sessionFixtures),
    messages: structuredClone(messageFixtures),
    indexes: structuredClone(indexFixtures),
    evaluations: structuredClone(evaluationFixtures),
    settings: structuredClone(defaultSettings),
    sequence: 100,
  }
}

let database = createDatabase()

export function getMockDatabase(): MockDatabase {
  return database
}

export function resetMockDatabase(): void {
  database = createDatabase()
}

export function nextMockId(prefix: string): string {
  database.sequence += 1
  return `${prefix}-${String(database.sequence).padStart(3, '0')}`
}

export function nextMockTimestamp(): string {
  const base = new Date(BASE_TIME).getTime()
  const offset = database.sequence * 1_000
  return new Date(base + offset).toISOString()
}

export function cloneValue<T>(value: T): T {
  return structuredClone(value)
}
