import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { SubscriptionUpdate } from '../api/types'
import { useApp } from '../store'

// Подписки (D6): реальный CRUD через API + лента обновлений (/updates).
export function SubscriptionsPage() {
  const { subs, addSub, removeSub, markSubRead } = useApp()
  const [active, setActive] = useState<string | null>(null)
  const [updates, setUpdates] = useState<SubscriptionUpdate[]>([])
  const [loadingUpd, setLoadingUpd] = useState(false)
  const [newQuery, setNewQuery] = useState('')
  const [newEmail, setNewEmail] = useState('')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Первичная загрузка: подхватываем серверный/мок-список (для demo), мержим в store.
  useEffect(() => {
    api.subscriptions().then((list) => list.forEach(addSub)).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!active && subs[0]) setActive(subs[0].id)
  }, [subs, active])

  useEffect(() => {
    if (!active) {
      setUpdates([])
      return
    }
    setLoadingUpd(true)
    markSubRead(active)
    api
      .subscriptionUpdates(active)
      .then(setUpdates)
      .catch(() => setUpdates([]))
      .finally(() => setLoadingUpd(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active])

  async function create() {
    const q = newQuery.trim()
    if (!q) return
    setCreating(true)
    setError(null)
    try {
      const s = await api.createSubscription(q, newEmail.trim() || undefined)
      addSub(s)
      setActive(s.id)
      setNewQuery('')
      setNewEmail('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка создания подписки')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-8 space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-white">Подписки и уведомления</h1>
        <p className="text-slate-400 mt-1">
          Сохранённые запросы: при поступлении новых релевантных документов формируется лента обновлений.
        </p>
      </header>

      {/* Создание подписки */}
      <div className="card p-4 space-y-2">
        <div className="flex gap-2">
          <input
            value={newQuery}
            onChange={(e) => setNewQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && create()}
            placeholder="Новый сохранённый запрос…"
            className="flex-1 rounded-lg bg-ink-800 border border-ink-600 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-accent"
          />
          <input
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
            placeholder="email (опц.)"
            className="w-44 rounded-lg bg-ink-800 border border-ink-600 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-accent"
          />
          <button onClick={create} disabled={creating || !newQuery.trim()} className="btn-accent">
            {creating ? '…' : '+ Подписаться'}
          </button>
        </div>
        {error && <p className="text-xs text-rose-300">{error}</p>}
      </div>

      <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
        {/* Список подписок */}
        <div className="space-y-2">
          {subs.length === 0 ? (
            <div className="card p-6 text-center text-sm text-slate-500">
              Пока нет подписок. Сохраните первый запрос выше.
            </div>
          ) : (
            subs.map((s) => (
              <div
                key={s.id}
                className={`card p-3 transition-colors ${active === s.id ? 'border-accent-dim' : 'hover:border-ink-600'}`}
              >
                <button onClick={() => setActive(s.id)} className="w-full text-left">
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-sm text-slate-200">{s.query}</span>
                    {s.n_new > 0 && <span className="chip bg-accent text-ink-900 shrink-0">{s.n_new} нов.</span>}
                  </div>
                  <div className="text-xs text-slate-500 mt-1">
                    создано {s.created_at.slice(0, 10)}
                    {s.email ? ` · ${s.email}` : ' · без email'}
                  </div>
                </button>
                <div className="flex justify-end mt-1">
                  <button
                    onClick={() => {
                      removeSub(s.id)
                      if (active === s.id) setActive(null)
                    }}
                    className="text-[11px] text-slate-500 hover:text-rose-300"
                  >
                    удалить
                  </button>
                </div>
              </div>
            ))
          )}
        </div>

        {/* Лента обновлений */}
        <div className="card p-5">
          <h3 className="font-semibold text-white mb-3">Лента обновлений</h3>
          {loadingUpd ? (
            <div className="space-y-2">
              <div className="skeleton h-12" />
              <div className="skeleton h-12" />
            </div>
          ) : updates.length === 0 ? (
            <p className="text-sm text-slate-500">
              {active ? 'Нет новых обновлений по выбранной подписке.' : 'Выберите подписку слева.'}
            </p>
          ) : (
            <ul className="space-y-3">
              {updates.map((u) => (
                <li key={u.doc_id} className="border-l-2 border-accent-dim pl-3">
                  <div className="text-sm text-slate-200">{u.title}</div>
                  <div className="text-xs text-slate-500 mt-0.5">
                    {u.year} · {u.doc_id} · добавлено {u.added_at}
                  </div>
                  <div className="text-xs text-accent-soft mt-0.5">{u.reason}</div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
