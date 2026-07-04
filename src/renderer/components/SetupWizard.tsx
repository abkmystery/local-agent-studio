import { useEffect, useMemo, useState } from 'react';
import {
  ArrowRight, Check, Cloud, Cpu, ExternalLink, HardDrive, KeyRound, Laptop,
  MemoryStick, ShieldCheck, Sparkles,
} from 'lucide-react';
import { api, formatBytes } from '../api';
import type {
  Agent, CatalogModel, GeminiConfig, Hardware, ModelDescriptor,
  ProviderModelInstall, ProviderStatus, Workflow,
} from '../types';
import { Loading, Notice } from './Common';
import { Logo } from './Logo';

type RuntimeState = { status: string; progress: number; detail: string; error?: string };
type DownloadState = { id: string; status: string; downloaded_bytes: number; total_bytes?: number; error?: string };
const delay = (milliseconds: number) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));

const providerCopy: Record<string, { title: string; summary: string; badge: string; cloud?: boolean }> = {
  gemini: { title: 'Connect free-tier Gemini', summary: 'Fast cloud intelligence. Requires a Google AI Studio key and sends selected agent prompts to Google.', badge: 'Optional cloud', cloud: true },
  llama_cpp: { title: 'Built-in llama.cpp', summary: 'Most private and simplest local option. The app installs and manages it for you.', badge: 'Recommended local' },
  ollama: { title: 'Ollama', summary: 'Use an existing Ollama installation and its local model library.', badge: 'Local' },
  lm_studio: { title: 'LM Studio', summary: 'Connect to LM Studio’s local server and downloaded models.', badge: 'Local · external app' },
};

const providerDefaults: Record<string, ProviderStatus> = {
  gemini: { id: 'gemini', name: 'Gemini 3.5 Flash', kind: 'external', available: false, base_url: 'https://generativelanguage.googleapis.com', detail: 'Choose this option to connect Google AI Studio.', license_name: 'Google Gemini API terms', redistributable: false },
  llama_cpp: { id: 'llama_cpp', name: 'Built-in llama.cpp', kind: 'embedded', available: false, base_url: 'http://127.0.0.1', detail: 'Install the built-in runtime to continue.', license_name: 'MIT', redistributable: true },
  ollama: { id: 'ollama', name: 'Ollama', kind: 'external', available: false, base_url: 'http://127.0.0.1:11434', detail: 'Ollama has not been detected yet.', license_name: 'MIT', redistributable: true },
  lm_studio: { id: 'lm_studio', name: 'LM Studio', kind: 'external', available: false, base_url: 'http://127.0.0.1:1234', detail: 'LM Studio has not been detected yet.', license_name: 'Proprietary desktop / MIT SDKs', redistributable: false },
};

export function completeProviderChoices(providers: ProviderStatus[]): ProviderStatus[] {
  return ['gemini', 'llama_cpp', 'ollama', 'lm_studio'].map(
    (id) => providers.find((provider) => provider.id === id) ?? providerDefaults[id],
  );
}

export function providerIsReady(
  providerId: string,
  providers: ProviderStatus[],
  models: ModelDescriptor[],
  geminiConfigured = false,
): boolean {
  const live = providers.find((provider) => provider.id === providerId)?.available ?? false;
  if (providerId === 'gemini') return live || geminiConfigured || models.some((model) => model.provider_id === 'gemini');
  if (providerId === 'ollama' || providerId === 'lm_studio') {
    return live || models.some((model) => model.provider_id === providerId);
  }
  return live;
}

export function SetupWizard({ onComplete }: { onComplete: () => void }) {
  const [step, setStep] = useState(0);
  const [hardware, setHardware] = useState<Hardware>();
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [selectedProviderId, setSelectedProviderId] = useState('');
  const [models, setModels] = useState<ModelDescriptor[]>([]);
  const [selected, setSelected] = useState<ModelDescriptor>();
  const [catalog, setCatalog] = useState<CatalogModel[]>([]);
  const [selectedCatalog, setSelectedCatalog] = useState<CatalogModel>();
  const [downloadProgress, setDownloadProgress] = useState<number>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [runtimeInstall, setRuntimeInstall] = useState<RuntimeState>();
  const [geminiConfig, setGeminiConfig] = useState<GeminiConfig>();
  const [geminiKey, setGeminiKey] = useState('');
  const [providerInstall, setProviderInstall] = useState<ProviderModelInstall>();
  const [loadingSetup, setLoadingSetup] = useState(true);

  const orderedProviders = useMemo(
    () => completeProviderChoices(providers),
    [providers],
  );
  const selectedProvider = orderedProviders.find((provider) => provider.id === selectedProviderId);
  const providerModels = models.filter((model) => model.provider_id === selectedProviderId);

  async function refreshEnvironment(providerId = selectedProviderId) {
    const [providerData, modelData, geminiData] = await Promise.all([
      api.get<ProviderStatus[]>('/api/providers'),
      api.get<ModelDescriptor[]>('/api/models'),
      api.get<GeminiConfig>('/api/providers/gemini/config'),
    ]);
    setProviders(providerData);
    setModels(modelData);
    setGeminiConfig(geminiData);
    setSelected((current) => {
      if (current && current.provider_id === providerId && modelData.some((model) => model.id === current.id && model.provider_id === current.provider_id)) return current;
      return modelData.find((model) => model.provider_id === providerId);
    });
    return { providerData, modelData };
  }

  async function loadSetup() {
    setLoadingSetup(true);
    setError(undefined);
    const results = await Promise.allSettled([
      api.get<Hardware>('/api/system/hardware'),
      api.get<ProviderStatus[]>('/api/providers'),
      api.get<ModelDescriptor[]>('/api/models'),
      api.get<RuntimeState>('/api/runtime/llama-cpp'),
      api.get<CatalogModel[]>('/api/catalog'),
      api.get<GeminiConfig>('/api/providers/gemini/config'),
    ]);
    const [hardwareResult, providersResult, modelsResult, runtimeResult, catalogResult, geminiResult] = results;
    if (hardwareResult.status === 'fulfilled') setHardware(hardwareResult.value);
    else setError(hardwareResult.reason instanceof Error ? hardwareResult.reason.message : 'The hardware check did not finish.');
    if (providersResult.status === 'fulfilled') setProviders(providersResult.value);
    if (modelsResult.status === 'fulfilled') setModels(modelsResult.value);
    if (runtimeResult.status === 'fulfilled') setRuntimeInstall(runtimeResult.value);
    if (catalogResult.status === 'fulfilled') {
      setCatalog(catalogResult.value);
      setSelectedCatalog(catalogResult.value.find((item) => item.starter && item.fits_disk) ?? catalogResult.value.find((item) => item.recommended && item.fits_disk) ?? catalogResult.value.find((item) => item.fits_disk));
    }
    if (geminiResult.status === 'fulfilled') setGeminiConfig(geminiResult.value);
    setLoadingSetup(false);
  }

  function useSafeHardwareDefaults() {
    const gib = 1024 ** 3;
    setHardware({
      os: 'Windows', architecture: 'x64', cpu: 'Hardware details unavailable',
      cpu_logical_cores: navigator.hardwareConcurrency || 4,
      ram_total_bytes: 8 * gib, ram_available_bytes: 4 * gib, gpus: [],
      disk_free_bytes: 0, recommended_profile: 'small_fast',
      recommended_parameter_range: '1B–4B quantized', recommended_context: 4096,
      plain_summary: 'Conservative settings are active. The private hardware check can be retried later.',
    });
    setError(undefined);
  }

  useEffect(() => { void loadSetup(); }, []);

  async function chooseProvider(providerId: string) {
    setSelectedProviderId(providerId);
    setSelected(models.find((model) => model.provider_id === providerId));
    setError(undefined);
    try {
      await refreshEnvironment(providerId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function connectGemini() {
    if (!geminiKey.trim()) return;
    setBusy(true);
    setError(undefined);
    try {
      const config = await api.put<GeminiConfig>('/api/providers/gemini/config', { api_key: geminiKey.trim() });
      setGeminiConfig(config);
      setGeminiKey('');
      const refreshed = await refreshEnvironment('gemini');
      setSelected(refreshed.modelData.find((model) => model.provider_id === 'gemini'));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function installLlamaCpp(): Promise<boolean> {
    setError(undefined);
    try {
      setRuntimeInstall(await api.post<RuntimeState>('/api/runtime/llama-cpp/install'));
      for (let attempt = 0; attempt < 600; attempt += 1) {
        await delay(750);
        const state = await api.get<RuntimeState>('/api/runtime/llama-cpp');
        setRuntimeInstall(state);
        if (state.status === 'ready') {
          await refreshEnvironment('llama_cpp');
          return true;
        }
        if (state.status === 'failed') throw new Error(state.error || state.detail);
      }
      throw new Error('Runtime installation timed out. Check the connection and try again.');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      return false;
    }
  }

  async function downloadManagedStarter() {
    if (!selectedCatalog) return;
    setBusy(true);
    setError(undefined);
    setDownloadProgress(0);
    try {
      if (!providers.some((provider) => provider.id === 'llama_cpp' && provider.available) && !await installLlamaCpp()) return;
      const download = await api.post<{ id: string }>('/api/models/download', { catalog_id: selectedCatalog.id, license_acknowledged: true });
      for (let attempt = 0; attempt < 86400; attempt += 1) {
        await delay(1000);
        const current = (await api.get<DownloadState[]>('/api/downloads')).find((item) => item.id === download.id);
        if (!current) continue;
        setDownloadProgress(current.total_bytes ? current.downloaded_bytes / current.total_bytes : 0);
        if (current.status === 'failed') throw new Error(current.error || 'Model download failed safely.');
        if (current.status === 'complete') {
          const refreshed = await refreshEnvironment('llama_cpp');
          setSelected(refreshed.modelData.find((item) => item.provider_id === 'llama_cpp' && item.id === selectedCatalog.filename));
          setDownloadProgress(1);
          return;
        }
      }
      throw new Error('Model download timed out. Partial downloads resume safely.');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function installProviderStarter() {
    if (!['ollama', 'lm_studio'].includes(selectedProviderId)) return;
    setBusy(true);
    setError(undefined);
    try {
      const started = await api.post<ProviderModelInstall>(`/api/providers/${selectedProviderId}/models/install-starter`);
      setProviderInstall(started);
      for (let attempt = 0; attempt < 86400; attempt += 1) {
        await delay(1000);
        const current = (await api.get<ProviderModelInstall[]>('/api/provider-model-installs')).find((item) => item.id === started.id);
        if (!current) continue;
        setProviderInstall(current);
        setDownloadProgress(current.progress);
        if (current.status === 'failed') throw new Error(current.error || current.detail);
        if (current.status === 'complete') {
          const refreshed = await refreshEnvironment(selectedProviderId);
          setSelected(refreshed.modelData.find((item) => item.provider_id === selectedProviderId));
          return;
        }
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    if (!selectedProvider?.available || !selected || selected.provider_id !== selectedProviderId) {
      setError('Choose one connected provider and one runnable model before continuing.');
      return;
    }
    setBusy(true);
    setError(undefined);
    try {
      const context = Math.min(hardware?.recommended_context ?? 4096, 4096);
      const researcher = await api.post<Agent>('/api/agents', {
        name: 'Researcher', description: 'Extracts useful facts from the supplied task.', provider_id: selected.provider_id,
        model_id: selected.id, instructions: 'You are a careful researcher. Extract facts, uncertainties, and useful context from the supplied material. Do not claim to browse the web unless a web tool is connected. Be concise.',
        config: { temperature: 0.2, num_ctx: context, num_predict: 128 },
      });
      const editor = await api.post<Agent>('/api/agents', {
        name: 'Editor', description: 'Turns the first agent’s result into a clear answer.', provider_id: selected.provider_id,
        model_id: selected.id, instructions: 'You are a precise editor. Turn the supplied material into a clear, useful final answer. Keep it concise.',
        config: { temperature: 0.3, num_ctx: context, num_predict: 128 },
      });
      await api.post<Workflow>('/api/workflows', {
        name: 'Research then write', description: 'A simple two-agent workflow.',
        spec: { version: '1.0', limits: { max_iterations: 4, timeout_seconds: 900 }, nodes: [
          { id: 'input', type: 'input', label: 'Your request', position: { x: 60, y: 180 }, config: {} },
          { id: 'research', type: 'agent', label: 'Researcher', position: { x: 330, y: 180 }, config: { agent_id: researcher.id } },
          { id: 'edit', type: 'agent', label: 'Editor', position: { x: 600, y: 180 }, config: { agent_id: editor.id } },
          { id: 'output', type: 'output', label: 'Final answer', position: { x: 870, y: 180 }, config: {} },
        ], edges: [
          { id: 'e1', source: 'input', target: 'research' }, { id: 'e2', source: 'research', target: 'edit' },
          { id: 'e3', source: 'edit', target: 'output' },
        ] },
      });
      await api.put('/api/settings', { onboarding_complete: true });
      onComplete();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  if (!hardware) return <div className="wizard-screen"><div className="wizard-card compact-wizard"><Logo size={68} className="wizard-logo" /><h1>Checking this PC</h1><p className="lead">This stays on your computer and normally takes only a few seconds.</p>{loadingSetup ? <Loading label="Reading this PC privately…" /> : <><Notice kind="error">{error || 'The hardware check could not finish.'}</Notice><div className="button-row"><button className="secondary" onClick={useSafeHardwareDefaults}>Continue with safe defaults</button><button className="primary" onClick={() => void loadSetup()}>Try hardware check again</button></div></>}</div></div>;
  const profile = hardware.recommended_profile.replace('_', ' ');
  const providerReady = providerIsReady(selectedProviderId, providers, models, geminiConfig?.configured);
  const selectedReady = Boolean(selected && selected.provider_id === selectedProviderId && providerReady);

  return <div className="wizard-screen"><div className="wizard-card">
    <div className="wizard-progress">{[0, 1, 2].map((item) => <span key={item} className={step >= item ? 'done' : ''} />)}</div>
    {step === 0 && <>
      <Logo size={68} className="wizard-logo" />
      <p className="eyebrow">Welcome to Local Agent Studio</p><h1>Your agent studio, without the setup maze</h1>
      <p className="lead">Choose private local AI or opt into Gemini’s cloud free tier. Nothing leaves this PC unless you deliberately select a cloud provider or network tool.</p>
      <div className="hardware-grid"><div><Cpu /><span><small>Processor</small><strong>{hardware.cpu || `${hardware.cpu_logical_cores} logical cores`}</strong></span></div><div><MemoryStick /><span><small>Memory</small><strong>{formatBytes(hardware.ram_total_bytes)}</strong></span></div><div><Laptop /><span><small>Graphics</small><strong>{hardware.gpus[0]?.name ?? 'CPU inference'}</strong></span></div><div><HardDrive /><span><small>Free space</small><strong>{formatBytes(hardware.disk_free_bytes)}</strong></span></div></div>
      <Notice kind="success"><span><strong>{profile}</strong> is the comfortable local fit. {hardware.plain_summary}</span></Notice>
      <button className="primary large" onClick={() => setStep(1)}>Choose how your agents think <ArrowRight size={18} /></button>
    </>}
    {step === 1 && <>
      <span className="wizard-icon"><Sparkles size={26} /></span><p className="eyebrow">Required · choose one</p><h1>Pick an AI provider</h1>
      <p className="lead">Gemini is the quick cloud route. The other three stay local. You can add more providers later.</p>
      <div className="provider-choice-grid">{orderedProviders.map((provider) => {
        const copy = providerCopy[provider.id];
        return <button key={provider.id} className={`${selectedProviderId === provider.id ? 'selected' : ''} ${copy.cloud ? 'featured' : ''}`} onClick={() => void chooseProvider(provider.id)}>
          <span className={`provider-orb ${provider.id}`}>{provider.id === 'gemini' ? <Sparkles size={21} /> : provider.id === 'llama_cpp' ? <Cpu size={21} /> : provider.name.slice(0, 1)}</span>
          <span><span className="provider-choice-title"><strong>{copy.title}</strong><em>{copy.badge}</em></span><small>{copy.summary}</small></span>
          {selectedProviderId === provider.id && <Check size={19} />}
        </button>;
      })}</div>

      {selectedProviderId === 'gemini' && !geminiConfig?.configured && <section className="setup-panel cloud-setup"><div className="setup-panel-head"><Cloud /><div><h3>Connect Gemini in three small steps</h3><p>Google handles the account. Local Agent Studio stores only the API key, encrypted for this Windows account.</p></div></div><ol className="setup-steps"><li><span>1</span><div><strong>Open Google AI Studio and sign in</strong><small>A new account usually receives a default project and API key after accepting Google’s terms.</small><a className="secondary link-button" href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer">Open Google AI Studio <ExternalLink size={14} /></a></div></li><li><span>2</span><div><strong>Create or copy a Gemini API key</strong><small>Use a key restricted to the Gemini API. Do not paste your Google password here.</small></div></li><li><span>3</span><div><strong>Paste the API key below</strong><label>Gemini API key<input type="password" value={geminiKey} onChange={(event) => setGeminiKey(event.target.value)} autoComplete="off" placeholder="Paste the key from AI Studio" /></label><button className="primary" disabled={busy || geminiKey.trim().length < 20} onClick={() => void connectGemini()}><KeyRound size={16} /> {busy ? 'Verifying…' : 'Verify and connect'}</button></div></li></ol><Notice><span>Gemini is not local: selected prompts and outputs go to Google. Google lists free-tier usage, but quotas vary by project and free-tier content may be used to improve Google products. <a href="https://aistudio.google.com/usage" target="_blank" rel="noreferrer">View your live usage</a>.</span></Notice></section>}
      {selectedProviderId === 'gemini' && geminiConfig?.configured && <Notice kind="success"><span><strong>Gemini 3.5 Flash is connected.</strong> The key is encrypted locally and never shown again.</span></Notice>}
      {selectedProviderId === 'llama_cpp' && !providerReady && <section className="setup-panel"><h3>Install the built-in local engine</h3><p>No administrator access is required. The runtime is downloaded from the official llama.cpp release and verified.</p><button className="primary" disabled={['discovering', 'downloading', 'installing'].includes(runtimeInstall?.status ?? '')} onClick={() => void installLlamaCpp()}>{runtimeInstall && !['idle', 'failed'].includes(runtimeInstall.status) ? `${Math.round(runtimeInstall.progress * 100)}% · ${runtimeInstall.detail}` : 'Install llama.cpp safely'}</button></section>}
      {selectedProviderId === 'ollama' && !providerReady && <Notice kind="error"><span>{selectedProvider?.detail || 'Ollama is not responding.'} <a href="https://ollama.com/download/windows" target="_blank" rel="noreferrer">Install or open Ollama</a>, then select this card again to refresh.</span></Notice>}
      {selectedProviderId === 'lm_studio' && !providerReady && <Notice kind="error"><span>{selectedProvider?.detail || 'LM Studio’s local server is not responding.'} <a href="https://lmstudio.ai/download" target="_blank" rel="noreferrer">Open LM Studio</a>, start its local API server, then select this card again to refresh.</span></Notice>}
      {error && <Notice kind="error">{error}</Notice>}
      <div className="button-row"><button className="secondary" onClick={() => setStep(0)}>Back</button><button className="primary" disabled={!selectedProviderId || !providerReady} onClick={() => setStep(2)}>Choose a model <ArrowRight size={18} /></button></div>
    </>}
    {step === 2 && <>
      <span className="wizard-icon"><ShieldCheck size={26} /></span><p className="eyebrow">Required · one runnable model</p><h1>{providerModels.length ? 'Choose your first model' : 'Add the smallest starter model'}</h1>
      <p className="lead">The starter is intentionally tiny and fast enough to verify the complete workflow. Add larger models whenever you want more quality.</p>
      {providerModels.length > 0 && <div className="model-picker">{providerModels.map((model) => <button key={`${model.provider_id}:${model.id}`} className={selected?.id === model.id ? 'selected' : ''} onClick={() => setSelected(model)}><span><strong>{model.name}</strong><small>{model.provider_id === 'gemini' ? 'Google cloud' : model.provider_id.replace('_', ' ')} · {model.quantization || 'managed model'}</small></span><span><small>License / terms</small><strong>{model.license_name}</strong></span>{selected?.id === model.id && <Check size={19} />}</button>)}</div>}
      {providerModels.length === 0 && selectedProviderId === 'llama_cpp' && <><div className="catalog-picker">{catalog.map((model) => <button key={model.id} disabled={!model.fits_disk} className={selectedCatalog?.id === model.id ? 'selected' : ''} onClick={() => setSelectedCatalog(model)}><span><strong>{model.name}</strong><small>{model.description}</small></span><span><strong>{formatBytes(model.size_bytes)}</strong><small>{model.license_name}{model.starter ? ' · Fastest setup' : model.recommended ? ' · Recommended' : ''}</small></span></button>)}</div>{selectedCatalog && <button className="primary large" disabled={busy || !selectedCatalog.fits_disk} onClick={() => void downloadManagedStarter()}>{busy ? `Downloading ${Math.round((downloadProgress ?? 0) * 100)}%` : `Download ${selectedCatalog.name}`}</button>}</>}
      {providerModels.length === 0 && ['ollama', 'lm_studio'].includes(selectedProviderId) && <section className="starter-model-card"><span className="provider-orb starter"><Sparkles size={22} /></span><div><h3>Qwen 2.5 0.5B Quick Start</h3><p>Apache-2.0 · Q4_K_M · approximately {selectedProviderId === 'ollama' ? '398 MB' : '491 MB'}</p><small>{selectedProviderId === 'ollama' ? 'Downloaded through Ollama’s official model API.' : 'Downloaded by LM Studio from Qwen’s official Hugging Face repository.'}</small></div><button className="primary" disabled={busy} onClick={() => void installProviderStarter()}>{busy ? `${Math.round((providerInstall?.progress ?? 0) * 100)}%` : 'Install smallest model'}</button></section>}
      {selectedProviderId !== 'gemini' && <p className="model-help-links">Want another model? <a href={selectedProviderId === 'ollama' ? 'https://docs.ollama.com/api/pull' : selectedProviderId === 'lm_studio' ? 'https://lmstudio.ai/docs/app/basics/download-model' : 'https://huggingface.co/models?library=gguf'} target="_blank" rel="noreferrer">Read the {selectedProvider?.name} model guide <ExternalLink size={12} /></a></p>}
      {providerInstall && <Notice kind={providerInstall.status === 'failed' ? 'error' : providerInstall.status === 'complete' ? 'success' : 'info'}>{providerInstall.detail}</Notice>}
      {error && <Notice kind="error">{error}</Notice>}
      <div className="button-row"><button className="secondary" onClick={() => setStep(1)}>Back</button><button className="primary" disabled={busy || !selectedReady} onClick={() => void finish()}>{busy ? 'Preparing…' : 'Create my studio'} <ArrowRight size={18} /></button></div>
    </>}
  </div></div>;
}
