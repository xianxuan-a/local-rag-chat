import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  getRuntimeAccessToken,
  onAuthenticationExpired,
  setRuntimeAccessToken,
} from '@/api/auth'
import type { ApiConfig } from '@/api/config'
import { HttpClient } from '@/api/http'
import { AppError } from '@/types'

const config: ApiConfig = {
  mode: 'real',
  baseUrl: 'http://127.0.0.1:8000',
  timeoutMs: 500,
}

function response(body: unknown, init: ResponseInit = {}): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input
  return input instanceof URL ? input.href : input.url
}

afterEach(() => {
  vi.useRealTimers()
  window.sessionStorage.clear()
})

describe('HttpClient', () => {
  it('serializes JSON and query parameters and exposes response headers', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        response(
          { code: 0, message: 'success', data: { ok: true } },
          { headers: { 'X-Request-ID': 'request-1' } },
        ),
      )
    const client = new HttpClient(config, {
      fetcher,
      accessToken: () => 'short-lived-token',
    })

    const result = await client.request('/api/example', {
      method: 'POST',
      query: { enabled: true, page: 2, omitted: undefined },
      json: { name: '文档' },
    })

    const [url, requestInit] = fetcher.mock.calls[0] ?? []
    expect(url === undefined ? '' : requestUrl(url)).toBe(
      'http://127.0.0.1:8000/api/example?enabled=true&page=2',
    )
    const headers = new Headers(requestInit?.headers)
    expect(headers.get('Content-Type')).toBe('application/json')
    expect(headers.get('Authorization')).toBe('Bearer short-lived-token')
    expect(requestInit?.body).toBe(JSON.stringify({ name: '文档' }))
    expect(result.headers.get('X-Request-ID')).toBe('request-1')
  })

  it('sends FormData without setting a multipart Content-Type boundary', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(response({ code: 0, message: 'success', data: {} }))
    const client = new HttpClient(config, { fetcher })
    const formData = new FormData()
    formData.set('file', new File(['content'], 'document.txt'))

    await client.request('/api/files/upload', {
      method: 'POST',
      formData,
    })

    const requestInit = fetcher.mock.calls[0]?.[1]
    expect(requestInit?.body).toBe(formData)
    expect(new Headers(requestInit?.headers).has('Content-Type')).toBe(false)
  })

  it('supports 204 and successful empty responses', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(null, { status: 204 }))
    const client = new HttpClient(config, { fetcher })

    await expect(client.request('/api/empty')).resolves.toMatchObject({
      data: undefined,
      status: 204,
    })
  })

  it('maps FastAPI envelopes and non-JSON failures without hiding status', async () => {
    const structured = new HttpClient(config, {
      fetcher: vi
        .fn<typeof fetch>()
        .mockResolvedValue(
          response(
            { code: 409, message: '知识库包含文件或会话，不能删除', data: null },
            { status: 409 },
          ),
        ),
    })
    await expect(structured.request('/api/conflict')).rejects.toMatchObject({
      code: '409',
      status: 409,
      kind: 'http',
      message: '知识库包含文件或会话，不能删除',
    })

    const nonJson = new HttpClient(config, {
      fetcher: vi
        .fn<typeof fetch>()
        .mockResolvedValue(new Response('gateway failure', { status: 502 })),
    })
    await expect(nonJson.request('/api/failure')).rejects.toMatchObject({
      code: 'HTTP_502',
      status: 502,
      kind: 'http',
    })
  })

  it('distinguishes network errors, timeout and caller cancellation', async () => {
    const network = new HttpClient(config, {
      fetcher: vi
        .fn<typeof fetch>()
        .mockRejectedValue(new TypeError('connection refused')),
    })
    await expect(network.request('/api/offline')).rejects.toMatchObject({
      code: 'NETWORK_UNREACHABLE',
      kind: 'network',
    })

    vi.useFakeTimers()
    const pendingFetch = vi.fn<typeof fetch>(
      (_input, requestInit) =>
        new Promise<Response>((_resolve, reject) => {
          requestInit?.signal?.addEventListener('abort', () => {
            reject(new DOMException('aborted', 'AbortError'))
          })
        }),
    )
    const timeout = new HttpClient(
      { ...config, timeoutMs: 100 },
      { fetcher: pendingFetch },
    )
    const timedRequest = timeout.request('/api/slow')
    const timedExpectation = expect(timedRequest).rejects.toMatchObject({
      code: 'HTTP_TIMEOUT',
      kind: 'timeout',
    })
    await vi.advanceTimersByTimeAsync(101)
    await timedExpectation

    const caller = new AbortController()
    const cancelledRequest = timeout.request('/api/cancel', {
      signal: caller.signal,
    })
    const cancelledExpectation = expect(cancelledRequest).rejects.toMatchObject({
      code: 'REQUEST_CANCELLED',
      kind: 'cancelled',
    })
    caller.abort()
    await cancelledExpectation
  })

  it('reports successful non-JSON responses as parse errors', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockImplementation(() =>
        Promise.resolve(new Response('not-json', { status: 200 })),
      )
    const client = new HttpClient(config, { fetcher })
    await expect(client.request('/api/not-json')).rejects.toMatchObject({
      kind: 'parse',
    })
    await expect(client.request('/api/not-json')).rejects.toBeInstanceOf(AppError)
  })

  it('invalidates an existing session when the backend returns 401', async () => {
    const expired = vi.fn()
    const unsubscribe = onAuthenticationExpired(expired)
    setRuntimeAccessToken('expired-session-token')
    const client = new HttpClient(config, {
      fetcher: vi
        .fn<typeof fetch>()
        .mockResolvedValue(
          response(
            { code: 401, message: '登录状态已过期', data: null },
            { status: 401 },
          ),
        ),
      accessToken: getRuntimeAccessToken,
    })

    await expect(client.request('/api/protected')).rejects.toMatchObject({
      status: 401,
    })
    expect(expired).toHaveBeenCalledOnce()
    expect(getRuntimeAccessToken()).toBeNull()
    unsubscribe()
  })

  it('parses NDJSON across UTF-8 byte and line boundaries', async () => {
    const bytes = new TextEncoder().encode(
      '{"type":"delta","content":"中文"}\n{"type":"done"}\n',
    )
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, 30))
        controller.enqueue(bytes.slice(30, 34))
        controller.enqueue(bytes.slice(34))
        controller.close()
      },
    })
    const client = new HttpClient(config, {
      fetcher: vi.fn<typeof fetch>().mockResolvedValue(
        new Response(stream, {
          headers: { 'Content-Type': 'application/x-ndjson; charset=utf-8' },
        }),
      ),
    })
    const events: unknown[] = []

    await client.streamNdjson(
      '/api/chat/stream',
      { json: {}, signal: new AbortController().signal },
      (event) => events.push(event),
    )

    expect(events).toEqual([{ type: 'delta', content: '中文' }, { type: 'done' }])
  })

  it('cancels the response reader when the caller stops an active stream', async () => {
    const cancelled = vi.fn()
    const bytes = new TextEncoder().encode('{"type":"delta","content":"partial"}\n')
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes)
      },
      cancel: cancelled,
    })
    const client = new HttpClient(config, {
      fetcher: vi.fn<typeof fetch>().mockResolvedValue(
        new Response(stream, {
          headers: { 'Content-Type': 'application/x-ndjson' },
        }),
      ),
    })
    const controller = new AbortController()

    await client.streamNdjson(
      '/api/chat/stream',
      { json: {}, signal: controller.signal },
      () => controller.abort(),
    )

    expect(cancelled).toHaveBeenCalledWith('caller_cancelled')
  })

  it('reports malformed NDJSON and invalid UTF-8 as parse errors', async () => {
    const malformed = new HttpClient(config, {
      fetcher: vi.fn<typeof fetch>().mockResolvedValue(
        new Response('{"type":\n', {
          headers: { 'Content-Type': 'application/x-ndjson' },
        }),
      ),
    })
    await expect(
      malformed.streamNdjson(
        '/api/chat/stream',
        { json: {}, signal: new AbortController().signal },
        () => undefined,
      ),
    ).rejects.toMatchObject({
      code: 'STREAM_EVENT_PARSE_FAILED',
      kind: 'parse',
    })

    const invalidUtf8 = new HttpClient(config, {
      fetcher: vi.fn<typeof fetch>().mockResolvedValue(
        new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(Uint8Array.of(0xc3, 0x28))
              controller.close()
            },
          }),
          { headers: { 'Content-Type': 'application/x-ndjson' } },
        ),
      ),
    })
    await expect(
      invalidUtf8.streamNdjson(
        '/api/chat/stream',
        { json: {}, signal: new AbortController().signal },
        () => undefined,
      ),
    ).rejects.toMatchObject({
      code: 'STREAM_UTF8_INVALID',
      kind: 'parse',
    })
  })
})
