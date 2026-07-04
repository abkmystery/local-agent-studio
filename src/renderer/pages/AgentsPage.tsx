import { useState } from 'react';
import { Bot, FileText, Plus, ShieldCheck, Trash2, Upload } from 'lucide-react';
import { api, formatBytes } from '../api';
import type { Agent, AgentSkill, ModelDescriptor } from '../types';
import { Empty, Header, Modal, Notice } from '../components/Common';

type AgentForm = {
  name: string;
  description: string;
  provider_id: string;
  model_id: string;
  instructions: string;
  config: {
    temperature: number; num_ctx: number; num_predict: number;
    capabilities: { attachments: boolean; file_access: boolean; web_access: boolean; code_execution: boolean; mcp: boolean };
  };
};

const emptyForm: AgentForm = {
  name: '', description: '', provider_id: '', model_id: '', instructions: '',
  config: { temperature: 0.2, num_ctx: 4096, num_predict: 128, capabilities: { attachments: true, file_access: true, web_access: false, code_execution: false, mcp: false } },
};

export function AgentsPage({ agents, models, reload }: { agents: Agent[]; models: ModelDescriptor[]; reload: () => Promise<void> }) {
  const [editing, setEditing] = useState<Agent | null | 'new'>(null);
  const [form, setForm] = useState<AgentForm>(emptyForm);
  const [skills, setSkills] = useState<AgentSkill[]>([]);
  const [pendingSkills, setPendingSkills] = useState<File[]>([]);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  function open(agent?: Agent) {
    setEditing(agent ?? 'new');
    setError(undefined);
    setSkills([]);
    setPendingSkills([]);
    setForm(agent ? {
      name: agent.name,
      description: agent.description,
      provider_id: agent.provider_id,
      model_id: agent.model_id,
      instructions: agent.instructions,
      config: {
        temperature: Number(agent.config.temperature ?? 0.2),
        num_ctx: Math.min(Number(agent.config.num_ctx ?? 4096), 4096),
        num_predict: Number(agent.config.num_predict ?? 128),
        capabilities: {
          attachments: Boolean((agent.config.capabilities as Record<string, boolean> | undefined)?.attachments ?? true),
          file_access: Boolean((agent.config.capabilities as Record<string, boolean> | undefined)?.file_access ?? true),
          web_access: Boolean((agent.config.capabilities as Record<string, boolean> | undefined)?.web_access ?? false),
          code_execution: Boolean((agent.config.capabilities as Record<string, boolean> | undefined)?.code_execution ?? false),
          mcp: Boolean((agent.config.capabilities as Record<string, boolean> | undefined)?.mcp ?? false),
        },
      },
    } : { ...emptyForm, config: { ...emptyForm.config, capabilities: { ...emptyForm.config.capabilities } }, provider_id: models[0]?.provider_id ?? '', model_id: models[0]?.id ?? '' });
    if (agent) {
      void api.get<AgentSkill[]>(`/api/agents/${agent.id}/skills`).then(setSkills).catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
    }
  }

  function chooseSkillFiles(files?: FileList | null) {
    if (!files) return;
    const accepted = Array.from(files).filter((file) => /\.(md|txt|json|ya?ml)$/i.test(file.name));
    const oversized = accepted.find((file) => file.size > 20_000);
    if (oversized) {
      setError(`${oversized.name} is larger than the 20 KB per-skill limit.`);
      return;
    }
    setPendingSkills((current) => {
      const byName = new Map(current.map((file) => [file.name.toLowerCase(), file]));
      accepted.forEach((file) => byName.set(file.name.toLowerCase(), file));
      return [...byName.values()].slice(0, 6);
    });
  }

  async function save() {
    setBusy(true); setError(undefined);
    try {
      if (!form.model_id) throw new Error('Connect a model before creating an agent.');
      const saved = editing && editing !== 'new'
        ? await api.put<Agent>(`/api/agents/${editing.id}`, form)
        : await api.post<Agent>('/api/agents', form);
      for (const file of pendingSkills) {
        const data = new FormData();
        data.append('file', file);
        await api.upload<AgentSkill>(`/api/agents/${saved.id}/skills`, data);
      }
      setPendingSkills([]);
      setEditing(null);
      await reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function remove(agent: Agent) {
    if (confirm(`Delete ${agent.name}? This is allowed only when no workflow still uses it.`)) {
      try {
        await api.delete(`/api/agents/${agent.id}`);
        await reload();
      } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    }
  }

  async function removeSkill(skill: AgentSkill) {
    if (!editing || editing === 'new') return;
    try {
      await api.delete(`/api/agents/${editing.id}/skills/${skill.id}`);
      setSkills((items) => items.filter((item) => item.id !== skill.id));
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
  }

  return <>
    <Header eyebrow="Specialists" title="Agents" subtitle="Give each agent one clear job, a model, and optional skill files it can follow." action={<button className="primary" onClick={() => open()}><Plus size={17} /> New agent</button>} />
    {error && !editing && <Notice kind="error">{error}</Notice>}
    {agents.length ? <div className="agent-grid">{agents.map((agent) => <article key={agent.id} onClick={() => open(agent)} tabIndex={0} onKeyDown={(event) => { if (event.key === 'Enter') open(agent); }}>
      <div className="agent-avatar"><Bot /></div>
      <div className="agent-card-head"><span className={`pill ${agent.provider_id === 'gemini' ? '' : 'green'}`}>{agent.provider_id === 'gemini' ? 'Cloud' : 'Local'}</span><button className="icon-button danger" onClick={(event) => { event.stopPropagation(); void remove(agent); }} aria-label={`Delete ${agent.name}`}><Trash2 size={16} /></button></div>
      <h3>{agent.name}</h3><p>{agent.description || agent.instructions.slice(0, 120)}</p>
      <footer><span>{agent.model_id}</span><span>{agent.provider_id.replace('_', ' ')}</span></footer>
    </article>)}</div> : <Empty icon={<Bot />} title="Make your first specialist" body="A useful agent has a narrow role, understandable instructions, and a model that fits the task." action={<button className="primary" onClick={() => open()}><Plus size={17} /> New agent</button>} />}
    {editing && <Modal title={editing === 'new' ? 'Create an agent' : `Edit ${editing.name}`} onClose={() => setEditing(null)}>
      <div className="form-stack">
        <label>Name<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="Researcher" /></label>
        <label>What is this agent for?<input value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="Finds reliable facts and caveats" /></label>
        <label>Model<select value={`${form.provider_id}:${form.model_id}`} onChange={(event) => { const [provider_id, ...rest] = event.target.value.split(':'); setForm({ ...form, provider_id, model_id: rest.join(':') }); }}><option value=":" disabled>Connect a model first</option>{models.map((model) => <option key={`${model.provider_id}:${model.id}`} value={`${model.provider_id}:${model.id}`}>{model.name} — {model.provider_id.replace('_', ' ')}</option>)}</select></label>
        <label>Instructions<textarea rows={7} value={form.instructions} onChange={(event) => setForm({ ...form, instructions: event.target.value })} placeholder="You are a careful researcher…" /></label>

        <section className="skill-files-box">
          <div><strong>Skill files</strong><small>Attach reusable Markdown, text, JSON, or YAML guidance. Up to six files, 20 KB each.</small></div>
          <label className="secondary skill-upload"><Upload size={15} /> Add skill files<input type="file" multiple accept=".md,.txt,.json,.yaml,.yml" onChange={(event) => { chooseSkillFiles(event.target.files); event.target.value = ''; }} /></label>
          {(skills.length > 0 || pendingSkills.length > 0) && <div className="skill-file-list">
            {skills.map((skill) => <div key={skill.id}><FileText size={15} /><span><strong>{skill.name}</strong><small>{formatBytes(skill.size_bytes)} · encrypted locally</small></span><button className="icon-button danger" aria-label={`Remove ${skill.name}`} onClick={() => void removeSkill(skill)}><Trash2 size={14} /></button></div>)}
            {pendingSkills.map((file) => <div key={file.name} className="pending"><FileText size={15} /><span><strong>{file.name}</strong><small>{formatBytes(file.size)} · added when the agent is saved</small></span><button className="icon-button danger" aria-label={`Remove pending ${file.name}`} onClick={() => setPendingSkills((items) => items.filter((item) => item.name !== file.name))}><Trash2 size={14} /></button></div>)}
          </div>}
        </section>

        <section className="skill-files-box permission-box">
          <div><strong><ShieldCheck size={16} /> Agent permissions</strong><small>These can only narrow the studio-wide controls in Settings. Privileged workflow functions must name the agent whose permissions they use.</small></div>
          {([
            ['attachments', 'Use attached files and images'],
            ['file_access', 'Read or create files in the approved workspace'],
            ['web_access', 'Use approved network and web tools'],
            ['code_execution', 'Authorize approval-gated Python snippets'],
            ['mcp', 'Authorize approval-gated MCP tools'],
          ] as const).map(([key, label]) => <label className="setting-row compact" key={key}><span><strong>{label}</strong></span><span className="switch"><input type="checkbox" checked={form.config.capabilities[key]} onChange={(event) => setForm({ ...form, config: { ...form.config, capabilities: { ...form.config.capabilities, [key]: event.target.checked } } })} /><span /></span></label>)}
        </section>

        <div className="split-fields">
          <label>Creativity<input type="number" min="0" max="2" step="0.1" value={form.config.temperature} onChange={(event) => setForm({ ...form, config: { ...form.config, temperature: Number(event.target.value) } })} /></label>
          <label>Working context<input type="number" min="512" max="4096" step="512" value={form.config.num_ctx} onChange={(event) => setForm({ ...form, config: { ...form.config, num_ctx: Number(event.target.value) } })} /><small>4,096 is the responsive default.</small></label>
        </div>
        <label>Maximum answer tokens<input type="number" min="32" max="256" step="32" value={form.config.num_predict} onChange={(event) => setForm({ ...form, config: { ...form.config, num_predict: Number(event.target.value) } })} /><small>128 is the responsive default; shorter answers finish faster.</small></label>
        {error && <Notice kind="error">{error}</Notice>}
        <div className="modal-actions"><button className="secondary" disabled={busy} onClick={() => setEditing(null)}>Cancel</button><button className="primary" disabled={busy || !form.name.trim() || !form.instructions.trim()} onClick={() => void save()}>{busy ? 'Saving…' : 'Save agent'}</button></div>
      </div>
    </Modal>}
  </>;
}
