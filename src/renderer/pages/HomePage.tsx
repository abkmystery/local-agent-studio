import { useState } from 'react';
import { ArrowRight, Bot, Boxes, Network, PlayCircle, ShieldCheck, Sparkles } from 'lucide-react';
import { api } from '../api';
import type { Agent, Page, ProviderStatus, Run, Workflow } from '../types';
import { timeAgo } from '../api';
import { Header } from '../components/Common';

export function HomePage({ agents, workflows, runs, providers, setPage, reload }: {
  agents: Agent[]; workflows: Workflow[]; runs: Run[]; providers: ProviderStatus[]; setPage: (page: Page) => void; reload: () => Promise<void>;
}) {
  const available = providers.filter((provider) => provider.available);
  const [goal, setGoal] = useState('');
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  async function draft() {
    if (!goal.trim()) { setPage('workflows'); return; }
    setBusy(true); setError(undefined);
    try { await api.post('/api/workflows/draft', { goal }); await reload(); setPage('workflows'); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  }
  return <>
    <Header eyebrow="Private by design" title="Good morning." subtitle="Build something useful without sending your thinking elsewhere." />
    <section className="hero-card">
      <div><span className="hero-icon"><Sparkles size={23} /></span><h2>What should your agents accomplish?</h2><p>Start from a small, understandable workflow. You can inspect every handoff before it runs.</p>
        <div className="goal-box"><input value={goal} onChange={(event) => setGoal(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && void draft()} placeholder="For example: research a topic, draft it, then ask me to approve" /><button className="primary" disabled={busy} onClick={() => void draft()}>{busy ? 'Drafting…' : 'Draft workflow'} <ArrowRight size={18} /></button></div>{error && <small className="hero-error">{error}</small>}</div>
      <div className="privacy-visual"><div className="orbit one"><Bot /></div><div className="orbit two"><Network /></div><div className="core"><ShieldCheck /></div></div>
    </section>
    <div className="metric-grid">
      <button onClick={() => setPage('models')}><Boxes /><span><strong>{available.length}</strong><small>Local engines ready</small></span></button>
      <button onClick={() => setPage('agents')}><Bot /><span><strong>{agents.length}</strong><small>Agents</small></span></button>
      <button onClick={() => setPage('workflows')}><Network /><span><strong>{workflows.length}</strong><small>Workflows</small></span></button>
      <button onClick={() => setPage('runs')}><PlayCircle /><span><strong>{runs.filter((run) => run.status === 'completed').length}</strong><small>Completed runs</small></span></button>
    </div>
    <section className="section-card"><div className="section-title"><div><h2>Recent activity</h2><p>A local record of what your workflows did.</p></div><button className="text-button" onClick={() => setPage('runs')}>View all <ArrowRight size={16} /></button></div>
      {runs.length ? <div className="activity-list">{runs.slice(0, 5).map((run) => <div key={run.id}><span className={`run-icon ${run.status}`}><PlayCircle size={17} /></span><span><strong>{workflows.find((item) => item.id === run.workflow_id)?.name ?? 'Workflow'}</strong><small>{run.input.slice(0, 90)}</small></span><span className={`pill ${run.status === 'completed' ? 'green' : run.status === 'failed' ? 'red' : ''}`}>{run.status.replace('_', ' ')}</span><time>{timeAgo(run.started_at)}</time></div>)}</div> : <div className="inline-empty">Your first run will appear here.</div>}
    </section>
  </>;
}
