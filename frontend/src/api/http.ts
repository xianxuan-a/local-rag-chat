import { notifyAuthenticationExpired, type AccessTokenProvider } from '@/api/auth'
import type { ApiConfig } from '@/api/config'
import { AppError } from '@/types'

export type QueryValue = string | number | boolean | null | undefined

export interface HttpRequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  query?: Record<string, QueryValue>
  json?: unknown
  formData?: FormData
  signal?: AbortSignal
  headers?: Record<string, string>
}

export interface NdjsonStreamOptions {
  json: unknown
  signal: AbortSignal
}

export interface HttpResponse<T> {
  data: T
  status: number
  headers: Headers
}

export interface HttpClientOptions {
  fetcher?: typeof fetch
  accessToken?: AccessTokenProvider
}

interface BackendErrorEnvelope {
  code: string | null
  message: string | null
  details: unknown
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function backendErrorFrom(value: unknown): BackendErrorEnvelope {
  if (!isRecord(value)) {
    return { code: null, message: null, details: value }
  }
  const code =
    typeof value.code === 'string' || typeof value.code === 'number'
      ? String(value.code)
      : null
  const detail = value.detail
  const message =
    typeof value.message === 'string'
      ? value.message
      : typeof detail === 'string'
        ? detail
        : null
  const details = 'data' in value ? value.data : detail
  return { code, message, details }
}

function safeUrl(baseUrl: string, path: string): URL {
  const normalizedPath = path.replace(/^\/+/, '')
  const resolvedBase = baseUrl.startsWith('/')
    ? new URL(baseUrl, window.location.origin).href
    : baseUrl
  return new URL(normalizedPath, `${resolvedBase.replace(/\/+$/, '')}/`)
}

function responseErrorMessage(status: number, backendMessage: string | null): string {
  if (backendMessage) return backendMessage
  if (status === 502 || status === 504) {
    return '后端服务不可达，请检查 FastAPI 是否已启动。'
  }
  return `请求失败（HTTP ${status}）。`
}

export class HttpClient {
  private readonly baseUrl: string
  private readonly timeoutMs: number
  private readonly fetcher: typeof fetch
  private readonly accessToken: AccessTokenProvider | undefined

  constructor(config: ApiConfig, options: HttpClientOptions = {}) {
    if (config.mode !== 'real' || config.baseUrl === null) {
      throw new AppError(
        'HTTP_CLIENT_CONFIG_INVALID',
        'HTTP 客户端只能使用完整的 Real API 配置创建。',
        null,
        { kind: 'config' },
      )
    }
    this.baseUrl = config.baseUrl
    this.timeoutMs = config.timeoutMs
    this.fetcher = options.fetcher ?? globalThis.fetch.bind(globalThis)
    this.accessToken = options.accessToken
  }

  async request<T>(
    path: string,
    options: HttpRequestOptions = {},
  ): Promise<HttpResponse<T>> {
    if (options.json !== undefined && options.formData !== undefined) {
      throw new AppError(
        'HTTP_BODY_INVALID',
        '同一请求不能同时发送 JSON 和 FormData。',
        null,
        { kind: 'config' },
      )
    }

    const url = safeUrl(this.baseUrl, path)
    for (const [key, value] of Object.entries(options.query ?? {})) {
      if (value !== undefined && value !== null) {
        url.searchParams.set(key, String(value))
      }
    }

    const headers = new Headers(options.headers)
    headers.set('Accept', 'application/json')
    const token = this.accessToken?.()
    if (token) headers.set('Authorization', `Bearer ${token}`)

    let body: BodyInit | undefined
    if (options.formData !== undefined) {
      body = options.formData
    } else if (options.json !== undefined) {
      headers.set('Content-Type', 'application/json')
      body = JSON.stringify(options.json)
    }

    const controller = new AbortController()
    let timedOut = false
    let callerCancelled = options.signal?.aborted === true
    const cancelFromCaller = (): void => {
      callerCancelled = true
      controller.abort()
    }
    options.signal?.addEventListener('abort', cancelFromCaller, { once: true })
    if (callerCancelled) controller.abort()
    const timeoutId = window.setTimeout(() => {
      timedOut = true
      controller.abort()
    }, this.timeoutMs)
    const cleanup = (): void => {
      window.clearTimeout(timeoutId)
      options.signal?.removeEventListener('abort', cancelFromCaller)
    }
    const transportError = (cause: unknown): AppError => {
      if (timedOut) {
        return new AppError('HTTP_TIMEOUT', '请求超时，请稍后重试。', null, {
          kind: 'timeout',
          cause,
        })
      }
      if (callerCancelled || options.signal?.aborted === true) {
        return new AppError('REQUEST_CANCELLED', '请求已取消。', null, {
          kind: 'cancelled',
          cause,
        })
      }
      return new AppError(
        'NETWORK_UNREACHABLE',
        '后端服务不可达，请检查 FastAPI 是否已启动。',
        null,
        { kind: 'network', cause },
      )
    }

    let response: Response
    try {
      const requestInit: RequestInit = {
        method: options.method ?? 'GET',
        headers,
        signal: controller.signal,
      }
      if (body !== undefined) requestInit.body = body
      response = await this.fetcher(url, requestInit)
    } catch (cause) {
      cleanup()
      throw transportError(cause)
    }

    const requestId = response.headers.get('X-Request-ID')
    let text: string
    try {
      text = await response.text()
    } catch (cause) {
      throw transportError(cause)
    } finally {
      cleanup()
    }
    let parsed: unknown
    if (text) {
      try {
        parsed = JSON.parse(text) as unknown
      } catch (cause) {
        if (response.ok) {
          throw new AppError(
            'RESPONSE_PARSE_FAILED',
            '后端返回了无法解析的响应。',
            null,
            {
              status: response.status,
              kind: 'parse',
              requestId,
              cause,
            },
          )
        }
        parsed = null
      }
    }

    if (!response.ok) {
      if (response.status === 401 && token) {
        notifyAuthenticationExpired()
      }
      const backendError = backendErrorFrom(parsed)
      throw new AppError(
        backendError.code ?? `HTTP_${response.status}`,
        responseErrorMessage(response.status, backendError.message),
        null,
        {
          status: response.status,
          kind: 'http',
          details: backendError.details ?? text,
          requestId,
        },
      )
    }

    return {
      data: parsed as T,
      status: response.status,
      headers: response.headers,
    }
  }

  async streamNdjson(
    path: string,
    options: NdjsonStreamOptions,
    onEvent: (event: unknown) => void,
  ): Promise<void> {
    const url = safeUrl(this.baseUrl, path)
    const headers = new Headers({
      Accept: 'application/x-ndjson',
      'Content-Type': 'application/json',
    })
    const token = this.accessToken?.()
    if (token) headers.set('Authorization', `Bearer ${token}`)

    const controller = new AbortController()
    let reader: ReadableStreamDefaultReader<Uint8Array> | null = null
    let timedOut = false
    let callerCancelled = options.signal.aborted
    let timeoutId = 0
    const resetTimeout = (): void => {
      window.clearTimeout(timeoutId)
      timeoutId = window.setTimeout(() => {
        timedOut = true
        controller.abort()
      }, this.timeoutMs)
    }
    const cancelFromCaller = (): void => {
      callerCancelled = true
      controller.abort()
      void reader?.cancel('caller_cancelled').catch(() => undefined)
    }
    options.signal.addEventListener('abort', cancelFromCaller, { once: true })
    if (callerCancelled) controller.abort()
    resetTimeout()

    const cleanup = (): void => {
      window.clearTimeout(timeoutId)
      options.signal.removeEventListener('abort', cancelFromCaller)
    }
    const transportError = (cause: unknown): AppError => {
      if (cause instanceof AppError) return cause
      if (timedOut) {
        return new AppError('HTTP_TIMEOUT', '流式响应等待超时，请稍后重试。', null, {
          kind: 'timeout',
          cause,
        })
      }
      if (callerCancelled || options.signal.aborted) {
        return new AppError('REQUEST_CANCELLED', '请求已取消。', null, {
          kind: 'cancelled',
          cause,
        })
      }
      return new AppError(
        'NETWORK_UNREACHABLE',
        '后端服务不可达，请检查 FastAPI 是否已启动。',
        null,
        { kind: 'network', cause },
      )
    }

    try {
      const response = await this.fetcher(url, {
        method: 'POST',
        headers,
        body: JSON.stringify(options.json),
        signal: controller.signal,
      })
      resetTimeout()
      const requestId = response.headers.get('X-Request-ID')
      if (!response.ok) {
        const text = await response.text()
        let parsed: unknown = null
        try {
          parsed = text ? (JSON.parse(text) as unknown) : null
        } catch {
          parsed = null
        }
        if (response.status === 401 && token) notifyAuthenticationExpired()
        const backendError = backendErrorFrom(parsed)
        throw new AppError(
          backendError.code ?? `HTTP_${response.status}`,
          responseErrorMessage(response.status, backendError.message),
          null,
          {
            status: response.status,
            kind: 'http',
            details: backendError.details ?? text,
            requestId,
          },
        )
      }
      if (!response.headers.get('content-type')?.includes('application/x-ndjson')) {
        throw new AppError(
          'STREAM_CONTENT_TYPE_INVALID',
          '后端返回了不兼容的流式响应。',
          null,
          { kind: 'parse', requestId },
        )
      }
      reader = response.body?.getReader() ?? null
      if (reader === null) {
        throw new AppError('STREAM_BODY_MISSING', '后端未返回流式正文。', null, {
          kind: 'parse',
          requestId,
        })
      }
      const decoder = new TextDecoder('utf-8', { fatal: true })
      const decode = (value?: AllowSharedBufferSource, stream = false): string => {
        try {
          return value === undefined
            ? decoder.decode()
            : decoder.decode(value, { stream })
        } catch (cause) {
          throw new AppError(
            'STREAM_UTF8_INVALID',
            '流式响应包含无效的 UTF-8 数据。',
            null,
            { kind: 'parse', requestId, cause },
          )
        }
      }
      let buffer = ''
      const consumeLine = (line: string): void => {
        const normalized = line.trim()
        if (!normalized) return
        let parsed: unknown
        try {
          parsed = JSON.parse(normalized) as unknown
        } catch (cause) {
          throw new AppError('STREAM_EVENT_PARSE_FAILED', '流式事件无法解析。', null, {
            kind: 'parse',
            requestId,
            cause,
          })
        }
        onEvent(parsed)
      }
      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          resetTimeout()
          buffer += decode(value, true)
          if (buffer.length > 1_048_576) {
            throw new AppError(
              'STREAM_EVENT_TOO_LARGE',
              '单个流式事件超过允许大小。',
              null,
              { kind: 'parse', requestId },
            )
          }
          let newline = buffer.indexOf('\n')
          while (newline >= 0) {
            consumeLine(buffer.slice(0, newline))
            buffer = buffer.slice(newline + 1)
            newline = buffer.indexOf('\n')
          }
        }
        buffer += decode()
        consumeLine(buffer)
      } finally {
        if (callerCancelled || timedOut) {
          try {
            await reader.cancel(callerCancelled ? 'caller_cancelled' : 'idle_timeout')
          } catch {
            // The fetch abort may already have errored the reader.
          }
        }
        reader.releaseLock()
        reader = null
      }
    } catch (cause) {
      throw transportError(cause)
    } finally {
      cleanup()
    }
  }
}
