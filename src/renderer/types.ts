export type Page = 'home' | 'models' | 'agents' | 'workflows' | 'runs' | 'resources' | 'settings';

export interface ProviderStatus {
  id: string;
  name: string;
  kind: 'embedded' | 'external';
  available: boolean;
  base_url: string;
  detail: string;
  license_name: string;
  redistributable: boolean;
}

export interface GeminiConfig {
  configured: boolean;
  model_id: string;
  ai_studio_url: string;
  quota_url: string;
  free_tier_note: string;
}

export interface EmailConfig {
  configured: boolean;
  provider: 'gmail' | 'outlook' | 'yahoo' | 'custom';
  sender_email: string;
  sender_name: string;
  username: string;
  host: string;
  port: number;
  security: 'ssl' | 'starttls';
  password_saved: boolean;
}

export interface ProviderModelInstall {
  id: string;
  provider_id: string;
  model_id: string;
  display_name: string;
  status: 'queued' | 'downloading' | 'complete' | 'failed';
  progress: number;
  detail: string;
  downloaded_bytes: number;
  total_bytes?: number;
  error?: string;
}

export interface Hardware {
  os: string;
  architecture: string;
  cpu: string;
  cpu_logical_cores: number;
  ram_total_bytes: number;
  ram_available_bytes: number;
  gpus: { name: string; memory_bytes?: number; backend: string }[];
  disk_free_bytes: number;
  recommended_profile: string;
  recommended_parameter_range: string;
  recommended_context: number;
  plain_summary: string;
}

export interface ModelDescriptor {
  id: string;
  name: string;
  provider_id: string;
  publisher: string;
  source_url?: string;
  license_name: string;
  license_url?: string;
  quantization?: string;
  size_bytes?: number;
  context_length?: number;
  capabilities: string[];
  installed: boolean;
  loaded: boolean;
}

export interface CatalogModel {
  id: string;
  name: string;
  profile: 'small_fast' | 'balanced' | 'highest_quality';
  description: string;
  publisher: string;
  filename: string;
  size_bytes: number;
  memory_estimate_bytes: number;
  context_length: number;
  license_name: string;
  license_url: string;
  capabilities: string[];
  starter?: boolean;
  recommended: boolean;
  fits_disk: boolean;
  installed: boolean;
}

export interface Agent {
  id: string;
  name: string;
  description: string;
  provider_id: string;
  model_id: string;
  instructions: string;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface AgentSkill {
  id: string;
  agent_id: string;
  name: string;
  media_type: string;
  size_bytes: number;
  created_at: string;
}

export interface WorkflowNode {
  id: string;
  type: 'input' | 'agent' | 'function' | 'parallel' | 'router' | 'approval' | 'review' | 'output';
  label: string;
  position: { x: number; y: number };
  config: Record<string, unknown>;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  condition?: string;
}

export interface Workflow {
  id: string;
  name: string;
  description: string;
  spec: {
    version: '1.0';
    nodes: WorkflowNode[];
    edges: WorkflowEdge[];
    limits: Record<string, number>;
  };
  created_at: string;
  updated_at: string;
}

export interface ToolDefinition {
  id: string;
  name: string;
  description: string;
  approval_policy: 'never' | 'mutating' | 'always';
  execution: 'local';
  input_schema: Record<string, 'string' | 'object' | 'any'>;
  capability?: keyof StudioCapabilities;
  available?: boolean;
  unavailable_reason?: string;
}

export interface StudioCapabilities {
  attachments: boolean;
  file_access: boolean;
  web_access: boolean;
  code_execution: boolean;
  mcp: boolean;
}

export interface PythonRuntime {
  available: boolean;
  path: string;
  version?: string;
  source: 'detected' | 'custom' | 'missing';
  status: 'idle' | 'installing_manager' | 'installing_runtime' | 'ready' | 'ready_restart' | 'failed';
  detail: string;
  progress: number;
  error?: string;
}

export interface MCPServer {
  id: string;
  name: string;
  command: string;
  args: string[];
  enabled: boolean;
  transport: 'stdio';
  warning_acknowledged: boolean;
}

export interface RunStep {
  node_id: string;
  label: string;
  type: WorkflowNode['type'];
  status: 'pending' | 'running' | 'waiting_approval' | 'completed' | 'failed' | 'cancelled' | 'skipped';
  started_at?: string;
  finished_at?: string;
  output_preview?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
  error?: string;
}

export interface Run {
  id: string;
  workflow_id: string;
  status: string;
  input: string;
  output?: string;
  state: Record<string, unknown> & {
    steps?: RunStep[];
    pending_approval?: {
      reason?: string;
      instructions?: string;
      tool_id?: string;
      arguments?: Record<string, unknown>;
      preview?: string;
      allow_response?: boolean;
      response_label?: string;
    };
  };
  error?: string;
  prompt_tokens: number;
  completion_tokens: number;
  started_at: string;
  finished_at?: string;
}

export interface Settings {
  onboarding_complete: boolean;
  offline_mode: boolean;
  models_dir: string;
  workspace_dir: string;
  approved_folders: string[];
  approved_domains: string[];
  capabilities: StudioCapabilities;
}
