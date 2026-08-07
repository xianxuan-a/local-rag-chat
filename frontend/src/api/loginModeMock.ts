import type { LoginModePresentation } from '@/api/loginModeContract'

export const loginModePresentation: LoginModePresentation = {
  isMock: true,
  badge: 'MOCK MODE',
  submitMessage: 'Mock 模式不执行身份认证，也不会发送或保存这些凭证。',
  securityMessage: 'Mock 模式不会发出认证请求',
  footerLabel: '无需认证即可使用演示数据',
  workspaceLinkLabel: '进入工作区',
}
