import DOMPurify from 'dompurify'
import { marked } from 'marked'

const rawHtmlPattern = /<\/?[A-Za-z][^>]*>/gu

function escapeHtml(value: string): string {
  return value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
}

export function renderMarkdown(source: string): string {
  const escapedSource = source.replace(rawHtmlPattern, (tag) => escapeHtml(tag))
  const parsed = marked.parse(escapedSource, {
    async: false,
    breaks: true,
    gfm: true,
  })
  const sanitized = DOMPurify.sanitize(parsed, {
    ALLOWED_TAGS: [
      'p',
      'br',
      'strong',
      'em',
      'ul',
      'ol',
      'li',
      'code',
      'pre',
      'blockquote',
      'a',
      'table',
      'thead',
      'tbody',
      'tr',
      'th',
      'td',
      'hr',
    ],
    ALLOWED_ATTR: ['href', 'title'],
  })

  const template = document.createElement('template')
  template.innerHTML = sanitized
  for (const anchor of template.content.querySelectorAll('a')) {
    anchor.target = '_blank'
    anchor.rel = 'noopener noreferrer'
  }
  return template.innerHTML
}
