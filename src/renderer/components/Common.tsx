import { AlertCircle, CheckCircle2, LoaderCircle, X } from 'lucide-react';

export function Header({ eyebrow, title, subtitle, action }: {
  eyebrow?: string; title: string; subtitle?: string; action?: React.ReactNode;
}) {
  return <header className="page-header">
    <div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>
    {action && <div>{action}</div>}
  </header>;
}

export function Empty({ icon, title, body, action }: { icon: React.ReactNode; title: string; body: string; action?: React.ReactNode }) {
  return <div className="empty"><span className="empty-icon">{icon}</span><h3>{title}</h3><p>{body}</p>{action}</div>;
}

export function Modal({ title, children, onClose, wide = false }: { title: string; children: React.ReactNode; onClose: () => void; wide?: boolean }) {
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section className={`modal ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
      <header><h2>{title}</h2><button className="icon-button" onClick={onClose} aria-label="Close"><X size={20} /></button></header>
      {children}
    </section>
  </div>;
}

export function Notice({ kind = 'info', children }: { kind?: 'info' | 'success' | 'error'; children: React.ReactNode }) {
  const Icon = kind === 'success' ? CheckCircle2 : kind === 'error' ? AlertCircle : AlertCircle;
  return <div className={`notice ${kind}`}><Icon size={18} />{children}</div>;
}

export function Loading({ label = 'Loading' }: { label?: string }) {
  return <div className="loading"><LoaderCircle className="spin" size={22} /> {label}</div>;
}
