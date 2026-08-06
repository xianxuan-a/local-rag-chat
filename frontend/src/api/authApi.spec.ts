import { describe, expect, it } from 'vitest'

import { mapAuthenticatedUser, mapAuthSession } from '@/api/authApi'

const userDto = {
  id: '00000000-0000-0000-0000-000000000001',
  username: 'bootstrap-admin',
  email: null,
  role: 'ADMIN',
  is_active: true,
  must_change_password: false,
  created_at: '2026-07-27T07:30:00+00:00',
}

describe('authentication API mappers', () => {
  it('maps the FastAPI user and token contracts', () => {
    expect(mapAuthenticatedUser(userDto)).toEqual({
      id: userDto.id,
      username: 'bootstrap-admin',
      email: null,
      role: 'ADMIN',
      isActive: true,
      mustChangePassword: false,
      createdAt: userDto.created_at,
    })
    expect(
      mapAuthSession({
        access_token: 'signed-token',
        token_type: 'bearer',
        expires_in: 1800,
        user: userDto,
      }),
    ).toMatchObject({
      accessToken: 'signed-token',
      tokenType: 'bearer',
      expiresIn: 1800,
      user: { username: 'bootstrap-admin' },
    })
  })

  it('rejects unknown roles and timestamps without timezone information', () => {
    expect(() => mapAuthenticatedUser({ ...userDto, role: 'OWNER' })).toThrow(
      '认证服务响应与前端契约不一致。',
    )
    expect(() =>
      mapAuthenticatedUser({
        ...userDto,
        created_at: '2026-07-27T07:30:00',
      }),
    ).toThrow('认证服务响应与前端契约不一致。')
  })
})
