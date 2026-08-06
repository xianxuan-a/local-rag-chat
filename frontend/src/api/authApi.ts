import { getRuntimeAccessToken } from '@/api/auth'
import { apiConfig } from '@/api/client'
import { HttpClient } from '@/api/http'
import { unwrapApiEnvelope } from '@/api/mappers'
import {
  AppError,
  type AuthenticatedUser,
  type AuthSession,
  type UserRole,
} from '@/types'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function contractError(field: string): never {
  throw new AppError(
    'API_CONTRACT_INVALID',
    '认证服务响应与前端契约不一致。',
    `字段 ${field} 缺失或类型无效。`,
    { kind: 'parse' },
  )
}

function stringField(value: Record<string, unknown>, field: string): string {
  const candidate = value[field]
  return typeof candidate === 'string' ? candidate : contractError(field)
}

function booleanField(value: Record<string, unknown>, field: string): boolean {
  const candidate = value[field]
  return typeof candidate === 'boolean' ? candidate : contractError(field)
}

function nullableStringField(
  value: Record<string, unknown>,
  field: string,
): string | null {
  const candidate = value[field]
  return candidate === null || typeof candidate === 'string'
    ? candidate
    : contractError(field)
}

export function mapAuthenticatedUser(value: unknown): AuthenticatedUser {
  if (!isRecord(value)) contractError('user')
  const role = stringField(value, 'role')
  if (!['ADMIN', 'USER'].includes(role)) contractError('user.role')
  const createdAt = stringField(value, 'created_at')
  if (
    !/(?:Z|[+-]\d{2}:\d{2})$/u.test(createdAt) ||
    Number.isNaN(Date.parse(createdAt))
  ) {
    contractError('user.created_at')
  }
  return {
    id: stringField(value, 'id'),
    username: stringField(value, 'username'),
    email: nullableStringField(value, 'email'),
    role: role as UserRole,
    isActive: booleanField(value, 'is_active'),
    mustChangePassword: booleanField(value, 'must_change_password'),
    createdAt,
  }
}

export function mapAuthSession(value: unknown): AuthSession {
  if (!isRecord(value)) contractError('session')
  const tokenType = stringField(value, 'token_type')
  if (tokenType.toLowerCase() !== 'bearer') contractError('session.token_type')
  const expiresIn = value.expires_in
  if (typeof expiresIn !== 'number' || !Number.isFinite(expiresIn) || expiresIn <= 0) {
    contractError('session.expires_in')
  }
  return {
    accessToken: stringField(value, 'access_token'),
    tokenType: 'bearer',
    expiresIn,
    user: mapAuthenticatedUser(value.user),
  }
}

function realClient(authenticated: boolean): HttpClient {
  if (apiConfig.mode !== 'real') {
    throw new AppError('AUTH_NOT_REQUIRED', 'Mock 模式不需要访问认证服务。', null, {
      kind: 'config',
    })
  }
  return new HttpClient(
    apiConfig,
    authenticated ? { accessToken: getRuntimeAccessToken } : {},
  )
}

export const authApi = {
  async register(
    username: string,
    email: string | null,
    password: string,
  ): Promise<AuthenticatedUser> {
    const response = await realClient(false).request<unknown>('/api/auth/register', {
      method: 'POST',
      json: { username, email, password },
    })
    return mapAuthenticatedUser(unwrapApiEnvelope(response.data))
  },

  async login(identity: string, password: string): Promise<AuthSession> {
    const response = await realClient(false).request<unknown>('/api/auth/login', {
      method: 'POST',
      json: { identity, password },
    })
    return mapAuthSession(unwrapApiEnvelope(response.data))
  },

  async getCurrentUser(): Promise<AuthenticatedUser> {
    const response = await realClient(true).request<unknown>('/api/auth/me')
    return mapAuthenticatedUser(unwrapApiEnvelope(response.data))
  },
}
