import { useEffect, useState } from 'react';
import {
  AlertTriangle, Ban, Check, CheckCircle2, Circle, Clock3, LoaderCircle,
  PlayCircle, RefreshCw, Square, X, XCircle,
} from 'lucide-react';
import { api, timeAgo } from '../api';
import type { Run, RunStep, Workflow } from '../types';
import { Empty, Header, Notice } from '../components/Common';

const ACTIVE = new Set(['queued', 'running', 'waiting_approval']);

function StepIcon({ status }: { status: RunStep['status'] }) {
  if (status === 'completed') return <CheckCircle2 size={18} />;
  if (status === 'running') return <LoaderCircle className="spin" size={18} />;
  if (status === 'waiting_approval') return <Clock3 size={18} />;
  if (status === 'failed') return <XCircle size={18} />;
  if (status === 'cancelled') return <Ban size={18} />;
  return <Circle size={18} />;
}

function elapsed(step: RunStep): string | undefined {
  if (!step.started_at || !step.finished_at) return undefined;
  const seconds = Math.max(0, (new Date(step.finished_at).getTime() - new Date(step.started_at).getTime()) / 1000);
  return seconds < 1 ? '<1s' : `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
}

export function RunsPage({ runs: initialRuns, workflows }: { runs: Run[]; workflows: Workflow[]; reload: () => Promise<void> }) {
  const [runs, setRuns] = useState<Run[]>(initialRuns);
  const [selected, setSelected] = useState<string>(initialRuns[0]?.id ?? '');
  const [error, setError] = useState<string>();
  const [response, setResponse] = useState('');
  const activeRuns = runs.some((item) => ACTIVE.has(item.status));

  async function refreshRuns() {
    try {
      setRuns(await api.get<Run[]>('/api/runs'));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  useEffect(() => {
    if (!activeRuns) return undefined;
    const timer = window.setInterval(() => void refreshRuns(), 700);
    return () => window.clearInterval(timer);
  }, [activeRuns]);
  useEffect(() => { setRuns(initialRuns); }, [initialRuns]);
  useEffect(() => {
    if ((!selected || !runs.some((item) => item.id === selected)) && runs[0]) setSelected(runs[0].id);
  }, [runs, selected]);

  const run = runs.find((item) => item.id === selected);

  async function approval(approved: boolean) {
    if (!run) return;
    setError(undefined);
    try {
      await api.post(`/api/runs/${run.id}/approval`, { approved, response });
      setResponse('');
      await refreshRuns();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function stop() {
    if (!run) return;
    setError(undefined);
    try {
      await api.post(`/api/runs/${run.id}/cancel`);
      await refreshRuns();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  return <>
    <Header eyebrow="Transparent execution" title="Runs" subtitle="Watch every node advance, inspect its result, approve guarded actions, or stop the flow." action={<button className="secondary" onClick={() => void refreshRuns()}><RefreshCw size={16} /> Refresh</button>} />
    {!runs.length ? <Empty icon={<PlayCircle />} title="Nothing has run yet" body="Open a workflow, give it a task, and its local execution record will appear here." /> : <div className="runs-layout">
      <aside className="run-list">{runs.map((item) => <button key={item.id} className={item.id === selected ? 'selected' : ''} onClick={() => setSelected(item.id)}>
        <span className={`run-icon ${item.status}`}>{item.status === 'waiting_approval' ? <Clock3 size={17} /> : item.status === 'failed' ? <AlertTriangle size={17} /> : item.status === 'cancelled' ? <Ban size={17} /> : <PlayCircle size={17} />}</span>
        <span><strong>{workflows.find((workflow) => workflow.id === item.workflow_id)?.name ?? 'Deleted workflow'}</strong><small>{item.input.slice(0, 54)}</small></span>
        <time>{timeAgo(item.started_at)}</time>
      </button>)}</aside>
      {run && <section className="run-detail">
        <div className="run-detail-head"><div><span className={`pill ${run.status === 'completed' ? 'green' : ['failed', 'cancelled'].includes(run.status) ? 'red' : ''}`}>{run.status.replace('_', ' ')}</span><h2>{workflows.find((workflow) => workflow.id === run.workflow_id)?.name ?? 'Workflow run'}</h2><p>{new Date(run.started_at).toLocaleString()}</p></div>
          <div className="run-head-actions">{ACTIVE.has(run.status) && <button className="secondary danger" onClick={() => void stop()}><Square size={14} /> Stop run</button>}<div className="token-count"><strong>{run.prompt_tokens + run.completion_tokens}</strong><small>tokens</small></div></div>
        </div>

        {run.status === 'waiting_approval' && <div className="approval-card"><Shield><Clock3 /></Shield><div><h3>{run.state.pending_approval?.reason ?? 'Waiting for you'}</h3><p>{run.state.pending_approval?.instructions ?? 'This workflow needs approval to continue.'}</p>{run.state.pending_approval?.tool_id && <code>{run.state.pending_approval.tool_id}</code>}{run.state.pending_approval?.preview && <details><summary>Review incoming data</summary><pre>{run.state.pending_approval.preview}</pre></details>}{run.state.pending_approval?.allow_response && <label>{run.state.pending_approval.response_label ?? 'Optional note'}<textarea rows={3} value={response} onChange={(event) => setResponse(event.target.value)} /></label>}</div><div><button className="secondary danger" onClick={() => void approval(false)}><X size={16} /> Reject & stop</button><button className="primary" onClick={() => void approval(true)}><Check size={16} /> Approve once</button></div></div>}
        {error && <Notice kind="error">{error}</Notice>}

        {run.state.steps && <section className="step-progress"><div className="section-title"><div><h3>Workflow progress</h3><p>Updates automatically while local inference is running.</p></div><span className="pill">{run.state.steps.filter((step) => step.status === 'completed').length}/{run.state.steps.length} complete</span></div><div className="step-list">{run.state.steps.map((step) => <div key={step.node_id} className={`step-row ${step.status}`}><span className="step-marker"><StepIcon status={step.status} /></span><div><div className="step-name"><strong>{step.label}</strong><span>{step.type.replace('_', ' ')}</span></div><small>{step.status.replace('_', ' ')}{elapsed(step) ? ` · ${elapsed(step)}` : ''}{(step.prompt_tokens || step.completion_tokens) ? ` · ${(step.prompt_tokens ?? 0) + (step.completion_tokens ?? 0)} tokens` : ''}</small>{step.output_preview && <details><summary>Show result</summary><pre>{step.output_preview}</pre></details>}{step.error && <p className="step-error">{step.error}</p>}</div></div>)}</div></section>}

        <div className="transcript"><section><h3>Input</h3><pre>{run.input}</pre></section>{run.output && <section><h3>Final output</h3><pre>{run.output}</pre></section>}{run.error && <section className="error-output"><h3>{run.status === 'cancelled' ? 'Stopped' : 'Error'}</h3><pre>{run.error}</pre></section>}</div>
      </section>}
    </div>}
  </>;
}

function Shield({ children }: { children: React.ReactNode }) { return <span className="approval-icon">{children}</span>; }
