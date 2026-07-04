import { NavLink } from 'react-router-dom'
import type { ReactNode } from 'react'
import { api } from '../api/client'
import type { Role } from '../api/types'
import { useApp, EDIT_ROLES, RESTRICTED_ROLE } from '../store'

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
      {/* Тёмная боковая навигация */}
      <aside className="w-60 shrink-0 bg-ink-850 border-r border-ink-700 flex flex-col">
        <div className="px-5 py-5 border-b border-ink-700">
          <div className="flex items-center gap-2.5">
            <div className="h-9 w-9 rounded-lg bg-gradient-to-br from-accent to-accent-dim flex items-center justify-center text-lg">
              🧬
            </div>
            <div>
              <div className="font-semibold text-white leading-tight">Научный клубок</div>
              <div className="text-[11px] text-slate-500 leading-tight">карта знаний R&D</div>
            </div>
          </div>
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
                    ? 'bg-accent-dim/40 text-white border border-accent-dim'
                    : 'text-slate-400 hover:bg-ink-700 hover:text-slate-200 border border-transparent'
                }`
              }
            >
              <span className="text-base">{n.icon}</span>
              {n.label}
              {n.badge === 'subs' && totalNew > 0 && (
                <span className="ml-auto chip bg-accent text-ink-900 px-1.5 py-0 text-[10px]">
                  {totalNew} нов.
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Переключатель роли (демо RBAC) */}
        <div className="px-4 py-3 border-t border-ink-700 space-y-2">
          <label className="text-[11px] uppercase tracking-wide text-slate-500">Роль (демо RBAC)</label>
          <select
            value={role}
            onChange={(e) => onRoleChange(e.target.value as Role)}
            className="w-full bg-ink-800 border border-ink-600 rounded-lg px-2.5 py-2 text-sm text-slate-200 focus:outline-none focus:border-accent"
          >
            {ROLES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
          {/* Индикаторы прав роли (RBAC-демо) */}
          <div className="flex flex-wrap gap-1 text-[10px]">
            {EDIT_ROLES.includes(role) && (
              <span className="chip bg-cyan-500/15 text-cyan-300 px-1.5 py-0">✎ правка графа</span>
            )}
            {role === RESTRICTED_ROLE && (
              <span className="chip bg-rose-500/15 text-rose-300 px-1.5 py-0">внутр. разделы скрыты</span>
            )}
            <span className="chip bg-ink-700 text-slate-500 px-1.5 py-0" title={token ?? 'нет токена'}>
              JWT {token ? '✓' : '—'}
            </span>
          </div>
          <div className="flex items-center gap-2 pt-1">
            <span
              className={`h-2 w-2 rounded-full ${api.mode === 'live' ? 'bg-emerald-400' : 'bg-amber-400'}`}
            />
            <span className="text-[11px] text-slate-500">
              {api.mode === 'live' ? `API: ${api.baseUrl}` : 'Режим: моки (demo)'}
            </span>
          </div>
        </div>
      </aside>

      {/* Контент */}
      <main className="flex-1 min-w-0 overflow-y-auto">{children}</main>
    </div>
  )
}
