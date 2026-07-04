import { useCallback, useEffect, useState } from 'react';
import { api } from './api';
import { useLoader } from './hooks';
import type { Agent, ModelDescriptor, Page, ProviderStatus, Run, Settings, ToolDefinition, Workflow } from './types';
import { Layout } from './components/Layout';
import { Loading, Notice } from './components/Common';
import { SetupWizard } from './components/SetupWizard';
import { Logo } from './components/Logo';
import { HomePage } from './pages/HomePage';
import { ModelsPage } from './pages/ModelsPage';
import { AgentsPage } from './pages/AgentsPage';
import { WorkflowsPage } from './pages/WorkflowsPage';
import { RunsPage } from './pages/RunsPage';
import { ResourcesPage } from './pages/ResourcesPage';
import { SettingsPage } from './pages/SettingsPage';

interface AppData {
  settings: Settings;
  providers: ProviderStatus[];
  models: ModelDescriptor[];
  agents: Agent[];
  workflows: Workflow[];
  runs: Run[];
  tools: ToolDefinition[];
}

async function loadApp(): Promise<AppData> {
  const [settings, providers, models, agents, workflows, runs, tools] = await Promise.all([
    api.get<Settings>('/api/settings'), api.get<ProviderStatus[]>('/api/providers'),
    api.get<ModelDescriptor[]>('/api/models'), api.get<Agent[]>('/api/agents'),
    api.get<Workflow[]>('/api/workflows'), api.get<Run[]>('/api/runs'),
    api.get<ToolDefinition[]>('/api/tools'),
  ]);
  return { settings, providers, models, agents, workflows, runs, tools };
}

export function App() {
  const [page, setPage] = useState<Page>('home');
  const loader = useLoader(loadApp, []);
  const reload = useCallback(async () => { await loader.reload(); }, [loader.reload]);
  useEffect(() => {
    const handler = (event: KeyboardEvent) => { if (event.ctrlKey && event.key.toLowerCase() === 'k') { event.preventDefault(); setPage('workflows'); } };
    window.addEventListener('keydown', handler); return () => window.removeEventListener('keydown', handler);
  }, []);
  if (loader.loading && !loader.data) return <div className="boot-screen"><Logo size={64} className="boot-logo" /><Loading label="Opening your studio…" /></div>;
  if (loader.error && !loader.data) return <div className="boot-screen"><Notice kind="error"><span><strong>Local service unavailable</strong><br />{loader.error}</span></Notice><button className="primary" onClick={() => void reload()}>Try again</button></div>;
  const data = loader.data!;
  if (!data.settings.onboarding_complete || data.models.length === 0) return <SetupWizard onComplete={() => void reload()} />;
  let content: React.ReactNode;
  if (page === 'models') content = <ModelsPage providers={data.providers} models={data.models} reload={reload} />;
  else if (page === 'agents') content = <AgentsPage agents={data.agents} models={data.models} reload={reload} />;
  else if (page === 'workflows') content = <WorkflowsPage workflows={data.workflows} agents={data.agents} tools={data.tools} reload={reload} onRunStarted={() => { void reload(); setPage('runs'); }} />;
  else if (page === 'runs') content = <RunsPage runs={data.runs} workflows={data.workflows} reload={reload} />;
  else if (page === 'resources') content = <ResourcesPage />;
  else if (page === 'settings') content = <SettingsPage settings={data.settings} reload={reload} />;
  else content = <HomePage agents={data.agents} workflows={data.workflows} runs={data.runs} providers={data.providers} setPage={setPage} reload={reload} />;
  return <Layout page={page} setPage={setPage} online>{content}</Layout>;
}
