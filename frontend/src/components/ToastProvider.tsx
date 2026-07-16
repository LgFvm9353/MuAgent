import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { CheckCircle2, CircleAlert, TriangleAlert, X } from 'lucide-react'
import type { ToastTone } from '../types/api'

type ToastInput = { tone: ToastTone; title: string; description?: string; dedupeKey?: string }
type Toast = ToastInput & { id: number }
const ToastContext = createContext<{ show: (toast: ToastInput) => void } | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const show = useCallback((toast: ToastInput) => {
    const id = Date.now()
    setToasts((items) => toast.dedupeKey && items.some((item) => item.dedupeKey === toast.dedupeKey) ? items : [...items, { ...toast, id }])
    window.setTimeout(() => setToasts((items) => items.filter((item) => item.id !== id)), 4500)
  }, [])
  const value = useMemo(() => ({ show }), [show])
  return <ToastContext.Provider value={value}>{children}<div className="fixed right-4 top-4 z-50 grid w-[min(24rem,calc(100vw-2rem))] gap-3">{toasts.map((toast) => { const Icon = toast.tone === 'success' ? CheckCircle2 : toast.tone === 'warning' ? TriangleAlert : CircleAlert; return <div key={toast.id} className={`toast toast-${toast.tone}`}><Icon size={19}/><div className="min-w-0 flex-1"><strong>{toast.title}</strong>{toast.description && <p>{toast.description}</p>}</div><button aria-label="关闭提示" onClick={() => setToasts((items) => items.filter((item) => item.id !== toast.id))}><X size={17}/></button></div> })}</div></ToastContext.Provider>
}

export function useToast() {
  const value = useContext(ToastContext)
  if (!value) throw new Error('useToast must be used inside ToastProvider')
  return value
}
