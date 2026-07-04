import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { QueryHistoryItem, Role, SearchResponse, Subscription } from './api/types'
import { api, setAuthToken } from './api/client'

const HISTORY_KEY = 'scitangle.history'
const SUBS_KEY = 'scitangle.subs'
const ROLE_KEY = 'scitangle.role'

interface AppState {
  role: Role
  setRole: (r: Role) => void
  token: string | null
  lastResult: SearchResponse | null
  setLastResult: (r: SearchResponse | null) => void
  lastQuery: string
  setLastQuery: (q: string) => void
  // История запросов (D7)
  history: QueryHistoryItem[]
  pushHistory: (item: QueryHistoryItem) => void
  clearHistory: () => void
  // Подписки (D6) — список ведём локально (живой GET-список отсутствует)
  subs: Subscription[]
  addSub: (s: Subscription) => void
  removeSub: (id: string) => void
  markSubRead: (id: string) => void
  totalNew: number
  // Глобальный модал документа (D4)
  openDocId: string | null
  openDocChunkId: string | null
  openDoc: (id: string | null, chunkId?: string | null) => void
  setOpenDocId: (id: string | null) => void
}

const Ctx = createContext<AppState | null>(null)

function load<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [role, setRoleState] = useState<Role>(() => load<Role>(ROLE_KEY, 'researcher'))
  const [token, setToken] = useState<string | null>(null)
  const [lastResult, setLastResult] = useState<SearchResponse | null>(null)
  const [lastQuery, setLastQuery] = useState('')
  const [history, setHistory] = useState<QueryHistoryItem[]>(() => load(HISTORY_KEY, []))
  const [subs, setSubs] = useState<Subscription[]>(() => load(SUBS_KEY, []))
  const [openDocId, setOpenDocId] = useState<string | null>(null)
  const [openDocChunkId, setOpenDocChunkId] = useState<string | null>(null)
  const openDoc = useCallback((id: string | null, chunkId?: string | null) => {
    setOpenDocId(id)
    setOpenDocChunkId(chunkId ?? null)
  }, [])

  // При смене роли — получить JWT и проставить в клиент (реальный Authorization)
  const setRole = useCallback((r: Role) => {
    setRoleState(r)
    localStorage.setItem(ROLE_KEY, JSON.stringify(r))
    api
      .authToken(r)
      .then((t) => {
        setToken(t.access_token)
        setAuthToken(t.access_token)
      })
      .catch(() => {
        setToken(null)
        setAuthToken(null)
      })
  }, [])

  // Первичное получение токена для стартовой роли
  useEffect(() => {
    setRole(role)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const pushHistory = useCallback((item: QueryHistoryItem) => {
    setHistory((prev) => {
      const next = [item, ...prev.filter((h) => h.query !== item.query)].slice(0, 25)
      localStorage.setItem(HISTORY_KEY, JSON.stringify(next))
      return next
    })
  }, [])

  const clearHistory = useCallback(() => {
    setHistory([])
    localStorage.removeItem(HISTORY_KEY)
  }, [])

  const persistSubs = (next: Subscription[]) => {
    localStorage.setItem(SUBS_KEY, JSON.stringify(next))
    return next
  }

  const addSub = useCallback((s: Subscription) => {
    setSubs((prev) => (prev.some((x) => x.id === s.id) ? prev : persistSubs([s, ...prev])))
  }, [])

  const removeSub = useCallback((id: string) => {
    setSubs((prev) => persistSubs(prev.filter((s) => s.id !== id)))
  }, [])

  const markSubRead = useCallback((id: string) => {
    setSubs((prev) => persistSubs(prev.map((s) => (s.id === id ? { ...s, n_new: 0 } : s))))
  }, [])

  const totalNew = useMemo(() => subs.reduce((acc, s) => acc + (s.n_new || 0), 0), [subs])

  return (
    <Ctx.Provider
      value={{
        role,
        setRole,
        token,
        lastResult,
        setLastResult,
        lastQuery,
        setLastQuery,
        history,
        pushHistory,
        clearHistory,
        subs,
        addSub,
        removeSub,
        markSubRead,
        totalNew,
        openDocId,
        openDocChunkId,
        openDoc,
        setOpenDocId,
      }}
    >
      {children}
    </Ctx.Provider>
  )
}

export function useApp() {
  const v = useContext(Ctx)
  if (!v) throw new Error('useApp must be used within AppProvider')
  return v
}

// Роли, которым доступен режим правки графа (D10)
export const EDIT_ROLES: Role[] = ['admin', 'project_lead']
// Роль с ограниченным доступом (D12: плашка «нет прав»)
export const RESTRICTED_ROLE: Role = 'external_partner'
