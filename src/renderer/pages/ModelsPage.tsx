import { useState } from 'react';
import { Activity, Boxes, CheckCircle2, ExternalLink, Gauge, RefreshCw } from 'lucide-react';
import { api, formatBytes } from '../api';
import type { ModelDescriptor, ProviderStatus } from '../types';
import { Empty, Header, Notice } from '../components/Common';

export function ModelsPage({ providers, models, reload }: { providers: ProviderStatus[]; models: ModelDescriptor[]; reload: () => Promise<void> }) {
  const [filter, setFilter] = useState('all');
  const [message, setMessage] = useState<string>();
  const [busy, setBusy] = useState<string>();
  const visible = filter === 'all' ? models : models.filter((model) => model.provider_id === filter);
  async function benchmark(model: ModelDescriptor) {
    setBusy(`${model.provider_id}:${model.id}`); setMessage(undefined);
    try {
      const result = await api.post<{ tokens_per_second?: number; structured_output_ok: boolean }>('/api/benchmarks', { provider_id: model.provider_id, model_id: model.id });
      setMessage(`Measured ${result.tokens_per_second?.toFixed(1) ?? 'unknown'} tokens/sec; structured output ${result.structured_output_ok ? 'passed' : 'needs care'}.`);
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); } finally { setBusy(undefined); }
  }
  return <>
    <Header eyebrow="Local intelligence" title="Models" subtitle="Everything here runs on hardware you control." action={<button className="secondary" onClick={() => void reload()}><RefreshCw size={16} /> Refresh</button>} />
    <div className="runtime-strip">{providers.map((provider) => <button key={provider.id} onClick={() => setFilter(provider.id)} className={filter === provider.id ? 'selected' : ''}><span className={`status-dot ${provider.available ? 'ready' : ''}`} /><span><strong>{provider.name}</strong><small>{provider.available ? 'Detected' : 'Not running'}</small></span><span className="pill">{provider.license_name}</span></button>)}</div>
    <div className="filter-row"><button className={filter === 'all' ? 'selected' : ''} onClick={() => setFilter('all')}>All installed</button>{providers.map((provider) => <button key={provider.id} className={filter === provider.id ? 'selected' : ''} onClick={() => setFilter(provider.id)}>{provider.name}</button>)}</div>
    {message && <Notice>{message}</Notice>}
    {visible.length ? <div className="model-grid">{visible.map((model) => <article key={`${model.provider_id}:${model.id}`}>
      <div className="model-card-top"><span className="model-symbol"><Boxes /></span><span className={`pill ${model.loaded ? 'green' : ''}`}>{model.loaded ? 'Loaded' : 'Installed'}</span></div>
      <h3>{model.name}</h3><p>{model.publisher} · {model.provider_id.replace('_', ' ')}</p>
      <dl><div><dt>Size</dt><dd>{formatBytes(model.size_bytes)}</dd></div><div><dt>Quantization</dt><dd>{model.quantization || 'Unknown'}</dd></div><div><dt>License</dt><dd>{model.license_name}</dd></div></dl>
      <div className="capabilities">{model.capabilities.map((capability) => <span key={capability}>{capability.replace('_', ' ')}</span>)}</div>
      <button className="secondary full" disabled={busy === `${model.provider_id}:${model.id}`} onClick={() => void benchmark(model)}><Gauge size={16} /> {busy ? 'Benchmarking…' : 'Run private benchmark'}</button>
    </article>)}</div> : <Empty icon={<Boxes />} title="No local models found" body="Add a GGUF file to the managed model folder, start Ollama, or enable LM Studio's local API server." action={<a className="primary link-button" href="https://ollama.com/download/windows" target="_blank" rel="noreferrer">Open official Ollama installer <ExternalLink size={16} /></a>} />}
  </>;
}
