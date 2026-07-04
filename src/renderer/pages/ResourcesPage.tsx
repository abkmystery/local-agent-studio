import { useEffect } from 'react';
import { Activity, Cpu, Gauge, HardDrive, MemoryStick, RefreshCw, Zap } from 'lucide-react';
import { api, formatBytes } from '../api';
import { useLoader } from '../hooks';
import { Header, Loading } from '../components/Common';

interface Snapshot {
  cpu_percent: number;
  ram_percent: number;
  ram_used_bytes: number;
  ram_total_bytes: number;
  disk_free_bytes: number;
  models_size_bytes: number;
  models: { name: string; size_bytes: number }[];
  providers: { id: string; name: string; available: boolean; detail: string }[];
  benchmarks: { id: string; provider_id: string; model_id: string; tokens_per_second?: number; first_token_ms?: number; structured_output_ok: number; measured_at: string }[];
}

function GaugeRing({ value, label, detail, icon }: { value: number; label: string; detail: string; icon: React.ReactNode }) {
  return <article className="gauge-card"><div className="gauge-ring" style={{ '--progress': `${Math.min(100, value) * 3.6}deg` } as React.CSSProperties}><div>{icon}<strong>{Math.round(value)}%</strong></div></div><h3>{label}</h3><p>{detail}</p></article>;
}

export function ResourcesPage() {
  const loader = useLoader(() => api.get<Snapshot>('/api/system/resources'), []);
  useEffect(() => { const timer = window.setInterval(() => void loader.reload(), 3000); return () => window.clearInterval(timer); }, [loader.reload]);
  if (!loader.data) return <Loading label="Reading local resources…" />;
  const data = loader.data;
  const diskPercent = data.models_size_bytes / Math.max(data.models_size_bytes + data.disk_free_bytes, 1) * 100;
  return <>
    <Header eyebrow="This computer" title="Resources" subtitle="Know what each local model costs in memory, disk, and time." action={<button className="secondary" onClick={() => void loader.reload()}><RefreshCw size={16} /> Refresh</button>} />
    <div className="gauge-grid"><GaugeRing value={data.cpu_percent} label="Processor" detail="Current local workload" icon={<Cpu size={19} />} /><GaugeRing value={data.ram_percent} label="Memory" detail={`${formatBytes(data.ram_used_bytes)} of ${formatBytes(data.ram_total_bytes)}`} icon={<MemoryStick size={19} />} /><GaugeRing value={diskPercent} label="Model storage" detail={`${formatBytes(data.models_size_bytes)} downloaded`} icon={<HardDrive size={19} />} /></div>
    <div className="resource-columns"><section className="section-card"><div className="section-title"><div><h2>Runtime health</h2><p>Bound to this computer only.</p></div><Activity size={20} /></div><div className="runtime-health">{data.providers.map((provider) => <div key={provider.id}><span className={`status-dot ${provider.available ? 'ready' : ''}`} /><span><strong>{provider.name}</strong><small>{provider.detail}</small></span><span className="pill">{provider.available ? 'Ready' : 'Offline'}</span></div>)}</div></section><section className="section-card"><div className="section-title"><div><h2>Private benchmarks</h2><p>Measured on this exact PC.</p></div><Zap size={20} /></div>{data.benchmarks.length ? <div className="benchmark-list">{data.benchmarks.map((benchmark) => <div key={benchmark.id}><span><strong>{benchmark.model_id}</strong><small>{benchmark.provider_id.replace('_', ' ')}</small></span><span><strong>{benchmark.tokens_per_second?.toFixed(1) ?? '—'}</strong><small>tokens/sec</small></span><span className={`pill ${benchmark.structured_output_ok ? 'green' : ''}`}>{benchmark.structured_output_ok ? 'JSON passed' : 'JSON unverified'}</span></div>)}</div> : <div className="inline-empty">Run a model benchmark to establish a local baseline.</div>}</section></div>
    <section className="section-card"><div className="section-title"><div><h2>Downloaded models</h2><p>Files you can remove without affecting workflows.</p></div><Gauge size={20} /></div>{data.models.length ? <div className="storage-list">{data.models.map((model) => <div key={model.name}><span><HardDrive size={17} /><strong>{model.name}</strong></span><span>{formatBytes(model.size_bytes)}</span></div>)}</div> : <div className="inline-empty">No managed GGUF files yet.</div>}</section>
  </>;
}
