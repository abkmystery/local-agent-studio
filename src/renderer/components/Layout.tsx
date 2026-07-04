import { Bot, Boxes, Gauge, Home, Network, PlayCircle, Settings as SettingsIcon } from 'lucide-react';
import type { Page } from '../types';
import { Logo } from './Logo';

const items: { page: Page; label: string; icon: typeof Home }[] = [
  { page: 'home', label: 'Home', icon: Home },
  { page: 'models', label: 'Models', icon: Boxes },
  { page: 'agents', label: 'Agents', icon: Bot },
  { page: 'workflows', label: 'Workflows', icon: Network },
  { page: 'runs', label: 'Runs', icon: PlayCircle },
  { page: 'resources', label: 'Resources', icon: Gauge },
  { page: 'settings', label: 'Settings', icon: SettingsIcon },
];

export function Layout({ page, setPage, children, online }: {
  page: Page;
  setPage: (page: Page) => void;
  children: React.ReactNode;
  online: boolean;
}) {
  return (
    <div className="shell">
      <aside className="sidebar">
        <button className="brand" onClick={() => setPage('home')} aria-label="Go home">
          <Logo size={40} className="brand-mark" />
          <span><strong>Local Agent</strong><small>Studio</small></span>
        </button>
        <nav aria-label="Main navigation">
          {items.map((item) => {
            const Icon = item.icon;
            return (
              <button key={item.page} className={page === item.page ? 'active' : ''} onClick={() => setPage(item.page)}>
                <Icon size={19} strokeWidth={1.8} /><span>{item.label}</span>
              </button>
            );
          })}
        </nav>
        <div className="privacy-card">
          <span className={`status-dot ${online ? 'ready' : ''}`} />
          <div><strong>{online ? 'Studio ready' : 'Connecting…'}</strong><small>Local by default. Cloud only when you choose it.</small></div>
        </div>
      </aside>
      <main className="main-content">{children}</main>
    </div>
  );
}
