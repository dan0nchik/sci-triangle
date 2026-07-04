// Утилиты скачивания файлов на стороне клиента (для экспорта D5/D7).

export function downloadText(filename: string, content: string, mime = 'text/plain') {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// Скачивание бинарного файла из base64 (pdf/xlsx с бэкенда — envelope с base64).
export function downloadBase64(filename: string, b64: string, mime: string) {
  const bin = atob(b64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  const blob = new Blob([bytes], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function csvCell(v: string): string {
  const needsQuote = /[",\n;]/.test(v)
  const escaped = v.replace(/"/g, '""')
  return needsQuote ? `"${escaped}"` : escaped
}

// CSV с BOM — корректно открывается в Excel как таблица (xlsx-совместимо).
export function downloadCsv(filename: string, rows: string[][]) {
  const body = rows.map((r) => r.map(csvCell).join(';')).join('\r\n')
  downloadText(filename, '﻿' + body, 'text/csv')
}
