import type { LoginModePresentation } from '@/api/loginModeContract'

export const loginModePresentation: LoginModePresentation = {
  isMock: false,
  badge: null,
  submitMessage: null,
  securityMessage: '凭证仅发送至本地认证服务',
  footerLabel: '需要账户？',
  workspaceLinkLabel: null,
}
