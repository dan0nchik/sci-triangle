import { NavLink } from 'react-router-dom'
import type { ReactNode } from 'react'
import { api } from '../api/client'
import type { Role } from '../api/types'
import { useApp, EDIT_ROLES, RESTRICTED_ROLE } from '../store'
import { BrandBlock } from './Logo'

const NAV = [
  { to: '/', label: 'Поиск', icon: '🔍', end: true },
  { to: '/graph', label: 'Граф', icon: '🕸' },
  { to: '/compare', label: 'Сравнение', icon: '⚖' },
  { to: '/dashboard', label: 'Дашборд', icon: '📊' },
  { to: '/subscriptions', label: 'Подписки', icon: '🔔', badge: 'subs' as const },
]

const ROLES: { value: Role; label: string }[] = [
  { value: 'researcher', label: 'Исследователь' },
  { value: 'analyst', label: 'Аналитик' },
  { value: 'project_lead', label: 'Рук. проекта' },
  { value: 'admin', label: 'Администратор' },
  { value: 'external_partner', label: 'Внешний партнёр' },
]

export function Layout({
  children,
  role,
  onRoleChange,
}: {
  children: ReactNode
  role: Role
  onRoleChange: (r: Role) => void
}) {
  const { totalNew, token } = useApp()
  return (
    <div className="flex h-full min-h-screen">
      {/* Светлая боковая навигация в фирменной стилистике «Норникель» */}
      <aside className="w-60 shrink-0 bg-ink-850 border-r border-ink-700 flex flex-col">
        {/* Фирменный блок: знак + продуктовое имя. Синяя «лента»-акцент по нижнему краю (стр. 26) */}
        <div className="px-5 py-5 border-b border-ink-700 relative">
          <BrandBlock />
          <span className="absolute left-0 right-0 -bottom-px h-[3px] bg-accent" />
        </div>

        <nav className="flex-1 px-3 py-4 space-y-1">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors ${
                  isActive
                    ? 'bg-accent/10 text-accent font-semibold border border-accent/25'
                    : 'text-fg-muted hover:bg-ink-900 hover:text-fg-body border border-transparent'
                }`
              }
            >
              <span className="text-base">{n.icon}</span>
              {n.label}
              {n.badge === 'subs' && totalNew > 0 && (
                <span className="ml-auto chip bg-accent text-white px-1.5 py-0 text-[10px]">
                  {totalNew} нов.
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Статус API (виден всегда) */}
        <div className="px-4 py-2.5 border-t border-ink-700 flex items-center gap-2">
          <span
            className={`h-2 w-2 rounded-full ${api.mode === 'live' ? 'bg-emerald-500' : 'bg-amber-500'}`}
          />
          <span className="text-[11px] text-fg-muted">
            {api.mode === 'live' ? `API: ${api.baseUrl}` : 'Режим: моки (demo)'}
          </span>
        </div>

        {/* Демо-режимы (доп. возможность) — де-акцентированный переключатель ролей.
            Свёрнут по умолчанию; роли отменены заказчиком, оставлены как демонстрация. */}
        <details className="group px-4 py-2 border-t border-ink-700">
          <summary className="flex items-center gap-2 cursor-pointer text-[11px] text-fg-faint hover:text-fg-muted list-none select-none">
            <span className="transition-transform group-open:rotate-90">›</span>
            Демо-режимы <span className="text-fg-faint/70">(доп. возможность)</span>
          </summary>
          <div className="mt-2 space-y-2">
            <label className="text-[10px] uppercase tracking-wide text-fg-faint">
              Контекст пользователя (демо)
            </label>
            <select
              value={role}
              onChange={(e) => onRoleChange(e.target.value as Role)}
              className="w-full bg-white border border-ink-600 rounded-lg px-2.5 py-1.5 text-xs text-fg-body focus:outline-none focus:border-accent"
            >
              {ROLES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
            <div className="flex flex-wrap gap-1 text-[10px]">
              {EDIT_ROLES.includes(role) && (
                <span className="chip bg-accent/10 text-accent px-1.5 py-0">✎ правка графа</span>
              )}
              {role === RESTRICTED_ROLE && (
                <span className="chip bg-ink-700 text-fg-muted px-1.5 py-0">открытые источники</span>
              )}
              <span className="chip bg-ink-700 text-fg-muted px-1.5 py-0" title={token ?? 'нет токена'}>
                JWT {token ? '✓' : '—'}
              </span>
            </div>
            <p className="text-[10px] text-fg-faint leading-relaxed">
              Разграничение доступа отменено заказчиком — показано как опциональная демонстрация.
            </p>
          </div>
        </details>

        {/* Подвал: конкурсная работа (без претензии на официальность) */}
        <div className="px-4 py-3 border-t border-ink-700">
          <p className="text-[10px] leading-relaxed text-fg-faint">
            Разработано для хакатона «Норникель» 2026. Конкурсная работа, использует
            фирменный стиль ПАО «ГМК «Норильский никель».
          </p>
        </div>
      </aside>

      {/* Контент */}
      <main className="flex-1 min-w-0 overflow-y-auto">{children}</main>
    </div>
  )
}
