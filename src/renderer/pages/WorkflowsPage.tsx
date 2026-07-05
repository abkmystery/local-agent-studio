import { useEffect, useMemo, useState } from 'react';
import {
  Background, Controls, Handle, MiniMap, Position, ReactFlow, addEdge,
  useEdgesState, useNodesState, type Connection, type Edge, type Node, type NodeProps,
} from '@xyflow/react';
import { Bot, Download, FolderOpen, Network, Paperclip, Play, Plus, Save, ShieldCheck, Trash2, Upload, Wrench, X } from 'lucide-react';
import { api } from '../api';
import type { Agent, MCPServer, ToolDefinition, Workflow, WorkflowNode } from '../types';
import { Empty, Header, Notice } from '../components/Common';

type CanvasData = {
  label: string;
  nodeType: WorkflowNode['type'];
  config: Record<string, unknown>;
  summary: string;
};
type StudioFlowNode = Node<CanvasData, 'studio'>;

const TOOL_DEFAULTS: Record<string, Record<string, unknown>> = {
  read_file: { path: '' },
  write_file: { path: '', content: '$input' },
  create_word: { path: '', title: '', content: '$input' },
  create_excel: { path: '', sheet_name: 'Data', data: '$input' },
  search_files: { query: '$input' },
  http_request: { url: 'https://', method: 'GET', body: '{}' },
  send_email: { to: '', subject: '', body: '$input' },
  transform: { operation: 'json_pretty', value: '$input' },
  python_code: { code: 'import json, sys\ndata = json.load(sys.stdin)\nprint(json.dumps({"result": data}))', input: '$input', timeout_seconds: '30' },
  mcp_call: { server_id: '', tool_name: '', arguments: '$input' },
};

function summaryFor(data: Pick<CanvasData, 'nodeType' | 'config'>, agents: Agent[], tools: ToolDefinition[]): string {
  if (data.nodeType === 'agent') {
    const agent = agents.find((item) => item.id === data.config.agent_id);
    return agent ? `${agent.name} · ${agent.provider_id.replace('_', ' ')}` : 'Choose an agent';
  }
  if (data.nodeType === 'function') {
    const name = tools.find((tool) => tool.id === data.config.tool_id)?.name ?? 'Choose a function';
    return data.config.tool_id === 'send_email' && data.config.approval_policy === 'never' ? `${name} · automatic` : name;
  }
  if (data.nodeType === 'approval') return String(data.config.reason ?? 'Human decision required');
  if (data.nodeType === 'review') return `${Number(data.config.max_iterations ?? 2)} revision rounds max`;
  if (data.nodeType === 'router') return 'Routes by matching text';
  if (data.nodeType === 'parallel') return 'Starts connected branches together';
  if (data.nodeType === 'input') return 'The task supplied at run time';
  return 'The final workflow result';
}

function StudioNode({ data }: NodeProps<StudioFlowNode>) {
  return <div className="studio-node-body">
    {data.nodeType !== 'input' && <Handle type="target" position={Position.Left} />}
    <small>{data.nodeType.replace('_', ' ')}</small>
    <strong>{data.label}</strong>
    <span>{data.summary}</span>
    {data.nodeType !== 'output' && <Handle type="source" position={Position.Right} />}
  </div>;
}

function canvasNodes(workflow: Workflow, agents: Agent[], tools: ToolDefinition[]): StudioFlowNode[] {
  return workflow.spec.nodes.map((node) => ({
    id: node.id,
    type: 'studio',
    position: node.position,
    data: { label: node.label, nodeType: node.type, config: node.config, summary: summaryFor({ nodeType: node.type, config: node.config }, agents, tools) },
    className: `flow-node type-${node.type}`,
  }));
}

function blankWorkflow(agents: Agent[]) {
  const agent = agents[0];
  return {
    name: 'Untitled workflow', description: 'A clear local workflow.',
    spec: { version: '1.0' as const, limits: { max_iterations: 4, timeout_seconds: 900 }, nodes: [
      { id: 'input', type: 'input' as const, label: 'Input', position: { x: 40, y: 180 }, config: {} },
      ...(agent ? [{ id: 'agent', type: 'agent' as const, label: agent.name, position: { x: 350, y: 180 }, config: { agent_id: agent.id } }] : []),
      { id: 'output', type: 'output' as const, label: 'Output', position: { x: 680, y: 180 }, config: {} },
    ], edges: agent ? [{ id: 'e-input-agent', source: 'input', target: 'agent' }, { id: 'e-agent-output', source: 'agent', target: 'output' }] : [{ id: 'e-input-output', source: 'input', target: 'output' }] },
  };
}

export function WorkflowsPage({ workflows, agents, tools, reload, onRunStarted }: {
  workflows: Workflow[];
  agents: Agent[];
  tools: ToolDefinition[];
  reload: () => Promise<void>;
  onRunStarted: () => void;
}) {
  const [selectedId, setSelectedId] = useState<string | undefined>(workflows[0]?.id);
  const selected = workflows.find((workflow) => workflow.id === selectedId);
  const [nodes, setNodes, onNodesChange] = useNodesState<StudioFlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selectedNode, setSelectedNode] = useState<string>();
  const [runInput, setRunInput] = useState('');
  const [runFiles, setRunFiles] = useState<File[]>([]);
  const [localPaths, setLocalPaths] = useState('');
  const [message, setMessage] = useState<string>();
  const [workflowName, setWorkflowName] = useState('');
  const [workflowDescription, setWorkflowDescription] = useState('');
  const [mcpServers, setMcpServers] = useState<MCPServer[]>([]);
  const [mcpTools, setMcpTools] = useState<Record<string, Array<{ name: string; description: string }>>>({});
  const nodeTypes = useMemo(() => ({ studio: StudioNode }), []);

  useEffect(() => {
    if (selected) {
      setNodes(canvasNodes(selected, agents, tools));
      setEdges(selected.spec.edges);
      setSelectedNode(undefined);
      setWorkflowName(selected.name);
      setWorkflowDescription(selected.description);
    }
  }, [selectedId, selected?.updated_at, agents, tools]);
  useEffect(() => {
    if ((!selectedId || !workflows.some((workflow) => workflow.id === selectedId)) && workflows[0]) setSelectedId(workflows[0].id);
  }, [workflows, selectedId]);
  useEffect(() => {
    void api.get<MCPServer[]>('/api/mcp/servers').then(setMcpServers).catch(() => setMcpServers([]));
  }, [tools]);

  const activeNode = nodes.find((node) => node.id === selectedNode);
  const activeTool = activeNode?.data.nodeType === 'function' ? tools.find((tool) => tool.id === activeNode.data.config.tool_id) : undefined;
  const onConnect = (connection: Connection) => setEdges((current) => addEdge({ ...connection, id: `e-${crypto.randomUUID()}` }, current));

  async function create() {
    try {
      const workflow = await api.post<Workflow>('/api/workflows', blankWorkflow(agents));
      await reload();
      setSelectedId(workflow.id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  function defaultConfig(type: WorkflowNode['type']): Record<string, unknown> {
    if (type === 'agent') return { agent_id: agents[0]?.id };
    if (type === 'approval') return { reason: 'Please review before this workflow continues', instructions: 'Check the incoming result for correctness and safety.', show_preview: true, allow_response: false, response_label: 'Revision note' };
    if (type === 'function') {
      const first = tools.find((tool) => tool.available !== false);
      return { tool_id: first?.id ?? 'transform', arguments: TOOL_DEFAULTS[first?.id ?? 'transform'] ?? {}, approval_policy: 'always' };
    }
    if (type === 'review') return { agent_id: agents[0]?.id, reviewer_agent_id: agents[1]?.id ?? agents[0]?.id, max_iterations: 2 };
    if (type === 'router') return { default_target: '', routes: [] };
    return {};
  }

  function addNode(type: WorkflowNode['type']) {
    const id = `${type}-${crypto.randomUUID().slice(0, 8)}`;
    const config = defaultConfig(type);
    const data: CanvasData = { label: type[0].toUpperCase() + type.slice(1), nodeType: type, config, summary: summaryFor({ nodeType: type, config }, agents, tools) };
    setNodes((items) => [...items, { id, type: 'studio', position: { x: 300 + items.length * 35, y: 90 + items.length * 45 }, data, className: `flow-node type-${type}` }]);
  }

  function updateActive(patch: Partial<CanvasData>) {
    setNodes((items) => items.map((node) => {
      if (node.id !== selectedNode) return node;
      const data = { ...node.data, ...patch };
      data.summary = summaryFor(data, agents, tools);
      return { ...node, data };
    }));
  }

  function updateConfig(patch: Record<string, unknown>) {
    if (!activeNode) return;
    updateActive({ config: { ...activeNode.data.config, ...patch } });
  }

  function updateArgument(key: string, value: unknown) {
    if (!activeNode) return;
    updateConfig({ arguments: { ...(activeNode.data.config.arguments as Record<string, unknown> ?? {}), [key]: value } });
  }

  async function save() {
    if (!selected) return;
    const specNodes = nodes.map((node) => ({ id: node.id, type: node.data.nodeType, label: node.data.label, position: node.position, config: node.data.config }));
    await api.put(`/api/workflows/${selected.id}`, { name: workflowName.trim() || selected.name, description: workflowDescription, spec: { ...selected.spec, nodes: specNodes, edges: edges.map(({ id, source, target }) => ({ id, source, target })) } });
    setMessage('Workflow saved locally.');
    await reload();
  }

  async function run() {
    if (!selected || !runInput.trim()) return;
    try {
      await save();
      const paths = localPaths.split('\n').map((item) => item.trim()).filter(Boolean);
      if (runFiles.length || paths.length) {
        const data = new FormData();
        data.append('input', runInput); data.append('local_paths', JSON.stringify(paths));
        runFiles.forEach((file) => data.append('files', file));
        await api.upload(`/api/workflows/${selected.id}/run-with-files`, data);
      } else {
        await api.post(`/api/workflows/${selected.id}/run`, { input: runInput });
      }
      setRunInput('');
      setRunFiles([]); setLocalPaths('');
      onRunStarted();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  async function removeWorkflow() {
    if (!selected || !confirm(`Delete “${workflowName || selected.name}” and its run history? This cannot be undone.`)) return;
    try {
      const next = workflows.find((workflow) => workflow.id !== selected.id);
      await api.delete(`/api/workflows/${selected.id}`);
      setSelectedId(next?.id);
      setSelectedNode(undefined);
      setMessage('Workflow deleted.');
      await reload();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  async function exportPack() {
    if (!selected) return;
    try {
      const blob = await api.download(`/api/workflows/${selected.id}/export`);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${(workflowName || selected.name).replace(/[^a-z0-9]+/gi, '-')}.agentpack`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  async function importPack(file?: File) {
    if (!file) return;
    try {
      const data = new FormData();
      data.append('file', file);
      const result = await api.upload<{ workflow_id: string }>('/api/agentpacks/import', data);
      await reload();
      setSelectedId(result.workflow_id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  function argumentControl(key: string, kind: string) {
    const argumentsValue = activeNode?.data.config.arguments as Record<string, unknown> | undefined;
    const value = String(argumentsValue?.[key] ?? '');
    if (key === 'method') return <select value={value || 'GET'} onChange={(event) => updateArgument(key, event.target.value)}>{['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((method) => <option key={method}>{method}</option>)}</select>;
    if (key === 'operation') return <select value={value || 'json_pretty'} onChange={(event) => updateArgument(key, event.target.value)}>{['json_pretty', 'csv_to_json', 'uppercase', 'lowercase', 'utc_now'].map((operation) => <option key={operation} value={operation}>{operation.replaceAll('_', ' ')}</option>)}</select>;
    if (key === 'server_id') return <select value={value} onChange={(event) => { const serverId = event.target.value; updateConfig({ arguments: { ...(argumentsValue ?? {}), server_id: serverId, tool_name: '' } }); if (serverId && !mcpTools[serverId]) void api.get<Array<{ name: string; description: string }>>(`/api/mcp/servers/${serverId}/tools`).then((items) => setMcpTools((current) => ({ ...current, [serverId]: items }))).catch((error) => setMessage(error instanceof Error ? error.message : String(error))); }}><option value="">Choose a connected MCP server</option>{mcpServers.filter((server) => server.enabled).map((server) => <option key={server.id} value={server.id}>{server.name}</option>)}</select>;
    if (key === 'tool_name') {
      const serverId = String(argumentsValue?.server_id ?? '');
      return <select value={value} disabled={!serverId} onFocus={() => { if (serverId && !mcpTools[serverId]) void api.get<Array<{ name: string; description: string }>>(`/api/mcp/servers/${serverId}/tools`).then((items) => setMcpTools((current) => ({ ...current, [serverId]: items }))).catch((error) => setMessage(error instanceof Error ? error.message : String(error))); }} onChange={(event) => updateArgument(key, event.target.value)}><option value="">{serverId ? 'Choose a tool' : 'Choose a server first'}</option>{(mcpTools[serverId] ?? []).map((tool) => <option key={tool.name} value={tool.name}>{tool.name}</option>)}</select>;
    }
    if (kind === 'object' || kind === 'any' || ['content', 'body', 'code'].includes(key)) return <textarea rows={key === 'code' ? 9 : 4} value={value} onChange={(event) => updateArgument(key, event.target.value)} placeholder={key === 'body' ? '{}' : 'Type a value or use $input'} spellCheck={key !== 'code'} />;
    return <input value={value} onChange={(event) => updateArgument(key, event.target.value)} placeholder={key === 'path' ? 'For example: reports/summary.docx' : key === 'url' ? 'https://allowed-domain.example/path' : 'Type a value or use $input'} />;
  }

  function updateRouterRule(index: number, patch: Record<string, string>) {
    if (!activeNode) return;
    const routes = [...(activeNode.data.config.routes as Array<Record<string, string>> ?? [])];
    routes[index] = { ...routes[index], ...patch };
    updateConfig({ routes });
  }

  function removeRouterRule(index: number) {
    if (!activeNode) return;
    const routes = [...(activeNode.data.config.routes as Array<Record<string, string>> ?? [])];
    routes.splice(index, 1);
    updateConfig({ routes });
  }

  return <>
    <Header eyebrow="Visual orchestration" title="Workflows" subtitle="Connect useful steps, configure what each one does, and watch execution live." action={<button className="primary" onClick={() => void create()}><Plus size={17} /> New workflow</button>} />
    {!workflows.length ? <Empty icon={<Network />} title="Connect your first workflow" body="Start with an input, one specialist, and an output. Complexity can earn its way in later." action={<button className="primary" onClick={() => void create()}><Plus size={17} /> Create workflow</button>} /> : <div className="workflow-layout">
      <aside className="workflow-list"><h3>Your workflows</h3>{workflows.map((workflow) => <button key={workflow.id} className={workflow.id === selectedId ? 'selected' : ''} onClick={() => setSelectedId(workflow.id)}><Network size={17} /><span><strong>{workflow.name}</strong><small>{workflow.spec.nodes.length} nodes</small></span></button>)}<label className="import-button"><Upload size={16} /> Import .agentpack<input type="file" accept=".agentpack" onChange={(event) => void importPack(event.target.files?.[0])} /></label></aside>
      <section className="canvas-panel">
        <div className="canvas-toolbar"><div className="node-tools"><button onClick={() => addNode('agent')}><Bot size={15} /> Agent</button><button onClick={() => addNode('parallel')}>Parallel</button><button onClick={() => addNode('router')}>Router</button><button onClick={() => addNode('review')}>Review</button><button onClick={() => addNode('approval')}><ShieldCheck size={15} /> Approval</button><button onClick={() => addNode('function')}><Wrench size={15} /> Function</button></div><div><button className="danger" onClick={() => void removeWorkflow()} title="Delete workflow"><Trash2 size={15} /> Delete</button><button onClick={() => void exportPack()}><Download size={15} /> Export</button><button className="primary small" onClick={() => void save().catch((error) => setMessage(error instanceof Error ? error.message : String(error)))}><Save size={15} /> Save</button></div></div>
        <div className="flow-wrap"><ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} onNodeClick={(_, node) => setSelectedNode(node.id)} fitView deleteKeyCode={['Backspace', 'Delete']}><Background gap={20} size={1} /><Controls /><MiniMap pannable zoomable /></ReactFlow></div>
        <div className="run-composer"><div className="run-bar"><input value={runInput} onChange={(event) => setRunInput(event.target.value)} placeholder="Give this workflow a task…" onKeyDown={(event) => event.key === 'Enter' && void run()} /><label className="icon-button attach-button" title="Attach files or images"><Paperclip size={17} /><input type="file" multiple accept=".txt,.md,.json,.csv,.yaml,.yml,.docx,.xlsx,.png,.jpg,.jpeg,.webp,.gif" onChange={(event) => { setRunFiles(Array.from(event.target.files ?? []).slice(0, 5)); event.target.value = ''; }} /></label><button className="primary" disabled={!runInput.trim()} onClick={() => void run()}><Play size={16} /> Run & watch</button></div><div className="local-path-row"><FolderOpen size={15} /><textarea rows={1} value={localPaths} onChange={(event) => setLocalPaths(event.target.value)} placeholder="Optional: approved local file path (one per line)" /></div>{runFiles.length > 0 && <div className="attachment-chips">{runFiles.map((file) => <span key={`${file.name}-${file.size}`}><Paperclip size={12} /> {file.name}<button aria-label={`Remove ${file.name}`} onClick={() => setRunFiles((items) => items.filter((item) => item !== file))}><X size={12} /></button></span>)}</div>}<small className="composer-help">Up to five supported documents or images, 12 MB total. Local paths must be inside the approved workspace.</small></div>
      </section>
      <aside className="inspector"><h3>Inspector</h3><div className="workflow-properties"><label>Workflow name<input value={workflowName} onChange={(event) => setWorkflowName(event.target.value)} /></label><label>Description<textarea rows={2} value={workflowDescription} onChange={(event) => setWorkflowDescription(event.target.value)} /></label></div>{activeNode ? <div className="form-stack"><span className="pill">{activeNode.data.nodeType}</span><p className="node-help">{activeNode.data.summary}</p><label>Node label<input value={activeNode.data.label} onChange={(event) => updateActive({ label: event.target.value })} /></label>
        {activeNode.data.nodeType === 'agent' && <label>Agent<select value={String(activeNode.data.config.agent_id ?? '')} onChange={(event) => updateConfig({ agent_id: event.target.value })}><option value="" disabled>Choose an agent</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name} — {agent.provider_id.replace('_', ' ')} · {agent.model_id}</option>)}</select><small>Agents from different providers can be connected in the same workflow.</small></label>}
        {activeNode.data.nodeType === 'review' && <><label>Writer<select value={String(activeNode.data.config.agent_id ?? '')} onChange={(event) => updateConfig({ agent_id: event.target.value })}>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name} — {agent.provider_id.replace('_', ' ')} · {agent.model_id}</option>)}</select></label><label>Reviewer<select value={String(activeNode.data.config.reviewer_agent_id ?? '')} onChange={(event) => updateConfig({ reviewer_agent_id: event.target.value })}>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name} — {agent.provider_id.replace('_', ' ')} · {agent.model_id}</option>)}</select></label><label>Maximum revision rounds<input type="number" min="1" max="6" value={Number(activeNode.data.config.max_iterations ?? 2)} onChange={(event) => updateConfig({ max_iterations: Number(event.target.value) })} /></label></>}
        {activeNode.data.nodeType === 'approval' && <><label>What should the user decide?<textarea rows={3} value={String(activeNode.data.config.reason ?? '')} onChange={(event) => updateConfig({ reason: event.target.value })} /></label><label>Review instructions<textarea rows={4} value={String(activeNode.data.config.instructions ?? '')} onChange={(event) => updateConfig({ instructions: event.target.value })} /></label><label className="check-row"><input type="checkbox" checked={Boolean(activeNode.data.config.show_preview ?? true)} onChange={(event) => updateConfig({ show_preview: event.target.checked })} /> Show incoming result</label><label className="check-row"><input type="checkbox" checked={Boolean(activeNode.data.config.allow_response)} onChange={(event) => updateConfig({ allow_response: event.target.checked })} /> Let the user add a note</label>{Boolean(activeNode.data.config.allow_response) && <label>Note label<input value={String(activeNode.data.config.response_label ?? '')} onChange={(event) => updateConfig({ response_label: event.target.value })} /></label>}</>}
        {activeNode.data.nodeType === 'function' && <><label>Function<select value={String(activeNode.data.config.tool_id ?? '')} onChange={(event) => updateConfig({ tool_id: event.target.value, arguments: TOOL_DEFAULTS[event.target.value] ?? {}, approval_policy: 'always' })}>{tools.map((tool) => <option key={tool.id} value={tool.id} disabled={tool.available === false}>{tool.name}{tool.available === false ? ' — setup required' : ''}</option>)}</select></label>{activeTool && <Notice kind={activeTool.available === false ? 'error' : activeTool.approval_policy === 'never' ? 'info' : 'success'}><span>{activeTool.description}<br /><strong>{activeTool.available === false ? activeTool.unavailable_reason : activeTool.approval_policy === 'never' ? 'Runs locally' : activeTool.id === 'send_email' && activeNode.data.config.approval_policy === 'never' ? 'Sends automatically for this node' : 'Approval required before consequential use'}</strong></span></Notice>}{activeTool?.id === 'send_email' && <><label>Approval before sending<select value={String(activeNode.data.config.approval_policy ?? 'always')} onChange={(event) => { const value = event.target.value; if (value === 'never' && !confirm('Allow this workflow node to send email automatically? Every run can send to its configured recipient without asking again.')) return; updateConfig({ approval_policy: value }); }}><option value="always">Ask every time (recommended)</option><option value="never">Send automatically for this node</option></select></label>{activeNode.data.config.approval_policy === 'never' && <Notice kind="error"><span><strong>Automatic sending is enabled.</strong> Anyone or any schedule that can start this workflow can send this message without another prompt.</span></Notice>}</>}{activeTool?.capability && ['web_access', 'code_execution', 'mcp'].includes(activeTool.capability) && <label>Authorized agent<select value={String(activeNode.data.config.agent_id ?? '')} onChange={(event) => updateConfig({ agent_id: event.target.value })}><option value="">Choose the agent whose permissions apply</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select><small>The studio master switch and this agent’s permission must both be on.</small></label>}{activeTool && Object.entries(activeTool.input_schema).map(([key, kind]) => <label key={key}>{key.replaceAll('_', ' ')}{argumentControl(key, kind)}<small>Use <code>$input</code> for the previous node’s result.</small></label>)}</>}
        {activeNode.data.nodeType === 'parallel' && <Notice>Connect multiple outgoing edges. They start together when memory allows; the scheduler may serialize model calls to keep the PC stable.</Notice>}
        {activeNode.data.nodeType === 'router' && <div className="router-editor"><Notice>Connect this router to every possible destination. The first matching text rule wins; unmatched input follows the default branch.</Notice><label>Default branch<select value={String(activeNode.data.config.default_target ?? '')} onChange={(event) => updateConfig({ default_target: event.target.value })}><option value="">Choose a destination</option>{nodes.filter((node) => node.id !== activeNode.id).map((node) => <option key={node.id} value={node.id}>{node.data.label}</option>)}</select></label><strong>Text rules</strong>{(activeNode.data.config.routes as Array<Record<string, string>> ?? []).map((route, index) => <div className="router-rule" key={`${index}-${route.target}`}><input value={route.contains ?? ''} onChange={(event) => updateRouterRule(index, { contains: event.target.value })} placeholder="If input contains…" /><select value={route.target ?? ''} onChange={(event) => updateRouterRule(index, { target: event.target.value })}><option value="">Destination</option>{nodes.filter((node) => node.id !== activeNode.id).map((node) => <option key={node.id} value={node.id}>{node.data.label}</option>)}</select><button className="icon-button danger" aria-label={`Remove router rule ${index + 1}`} onClick={() => removeRouterRule(index)}><Trash2 size={14} /></button></div>)}<button className="secondary" onClick={() => updateConfig({ routes: [...(activeNode.data.config.routes as Array<Record<string, string>> ?? []), { contains: '', target: '' }] })}><Plus size={14} /> Add text rule</button></div>}
        <button className="danger secondary" onClick={() => { setNodes((items) => items.filter((node) => node.id !== activeNode.id)); setEdges((items) => items.filter((edge) => edge.source !== activeNode.id && edge.target !== activeNode.id)); setSelectedNode(undefined); }}>Remove node</button>
      </div> : <p className="muted">Select a node to see what it does and configure it.</p>}</aside>
    </div>}
    {message && <div className="toast" onClick={() => setMessage(undefined)}>{message}</div>}
  </>;
}
