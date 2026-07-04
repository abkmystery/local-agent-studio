import { useEffect, useState } from 'react';
import { Cloud, Code2, ExternalLink, Folder, KeyRound, LockKeyhole, Mail, Network, Plus, RotateCcw, Send, ShieldCheck, Trash2, Unplug } from 'lucide-react';
import { api } from '../api';
import type { EmailConfig, GeminiConfig, MCPServer, PythonRuntime, Settings, StudioCapabilities } from '../types';
import { Header, Notice } from '../components/Common';

const blankEmail = {
  provider: 'gmail' as EmailConfig['provider'], sender_email: '', sender_name: '', username: '', password: '',
  host: 'smtp.gmail.com', port: 465, security: 'ssl' as EmailConfig['security'],
};

export function SettingsPage({ settings, reload }: { settings: Settings; reload: () => Promise<void> }) {
  const [message, setMessage] = useState<string>();
  const [error, setError] = useState<string>();
  const [domains, setDomains] = useState(settings.approved_domains.join(', '));
  const [approvedFolders, setApprovedFolders] = useState(settings.approved_folders.join('\n'));
  const [gemini, setGemini] = useState<GeminiConfig>();
  const [apiKey, setApiKey] = useState('');
  const [connecting, setConnecting] = useState(false);
  const [email, setEmail] = useState<EmailConfig>();
  const [emailForm, setEmailForm] = useState(blankEmail);
  const [testRecipient, setTestRecipient] = useState('');
  const [emailBusy, setEmailBusy] = useState(false);
  const [python, setPython] = useState<PythonRuntime>();
  const [pythonPath, setPythonPath] = useState('');
  const [pythonConsent, setPythonConsent] = useState(false);
  const [mcpServers, setMcpServers] = useState<MCPServer[]>([]);
  const [mcpForm, setMcpForm] = useState({ name: '', command: '', args: '', warning_acknowledged: false });

  async function loadGemini() {
    try { setGemini(await api.get<GeminiConfig>('/api/providers/gemini/config')); } catch { /* backend may still be upgrading */ }
  }
  async function loadEmail() {
    try {
      const value = await api.get<EmailConfig>('/api/integrations/email');
      setEmail(value);
      setEmailForm({
        provider: value.provider, sender_email: value.sender_email, sender_name: value.sender_name,
        username: value.username, password: '', host: value.host || 'smtp.gmail.com',
        port: value.port || 465, security: value.security || 'ssl',
      });
    } catch { /* backend may still be upgrading */ }
  }
  async function loadDeveloperRuntimes() {
    try {
      const [pythonState, servers] = await Promise.all([
        api.get<PythonRuntime>('/api/runtime/python'), api.get<MCPServer[]>('/api/mcp/servers'),
      ]);
      setPython(pythonState); setMcpServers(servers);
    } catch { /* optional developer integrations may still be upgrading */ }
  }
  useEffect(() => { void Promise.all([loadGemini(), loadEmail(), loadDeveloperRuntimes()]); }, []);

  async function update(patch: Partial<Settings>) {
    try {
      await api.put('/api/settings', patch);
      setMessage('Settings saved on this computer.'); setError(undefined);
      await reload();
    } catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
  }

  async function connectGemini() {
    setConnecting(true); setError(undefined); setMessage(undefined);
    try {
      await api.put('/api/providers/gemini/config', { api_key: apiKey.trim() });
      setApiKey(''); setMessage('Gemini 3.5 Flash is connected. The key is encrypted on this computer.');
      await loadGemini(); await reload();
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not verify this key.'); }
    finally { setConnecting(false); }
  }

  async function disconnectGemini() {
    setConnecting(true); setError(undefined);
    try {
      await api.delete('/api/providers/gemini/config');
      setMessage('Gemini disconnected and its saved key was removed.');
      await loadGemini(); await reload();
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not disconnect Gemini.'); }
    finally { setConnecting(false); }
  }

  function chooseEmailProvider(provider: EmailConfig['provider']) {
    const preset = provider === 'gmail' ? { host: 'smtp.gmail.com', port: 465, security: 'ssl' as const }
      : provider === 'outlook' ? { host: 'smtp.office365.com', port: 587, security: 'starttls' as const }
        : provider === 'yahoo' ? { host: 'smtp.mail.yahoo.com', port: 465, security: 'ssl' as const }
          : { host: '', port: 587, security: 'starttls' as const };
    setEmailForm((current) => ({ ...current, provider, ...preset }));
  }

  async function saveEmail() {
    setEmailBusy(true); setError(undefined); setMessage(undefined);
    try {
      const value = await api.put<EmailConfig>('/api/integrations/email', emailForm);
      setEmail(value); setEmailForm((current) => ({ ...current, password: '' }));
      setMessage('Sending account saved securely. Send a test before using it in a workflow.');
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not save the sending account.'); }
    finally { setEmailBusy(false); }
  }

  async function testEmail() {
    setEmailBusy(true); setError(undefined); setMessage(undefined);
    try {
      await api.post('/api/integrations/email/test', { to: testRecipient.trim() });
      setMessage(`Test email sent to ${testRecipient.trim()}.`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not send the test email.'); }
    finally { setEmailBusy(false); }
  }

  async function disconnectEmail() {
    setEmailBusy(true); setError(undefined);
    try {
      await api.delete('/api/integrations/email');
      setMessage('Sending account and saved password removed.');
      setEmail(undefined); setEmailForm({ ...blankEmail });
      await loadEmail();
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not remove the sending account.'); }
    finally { setEmailBusy(false); }
  }

  async function updateCapability(key: keyof StudioCapabilities, enabled: boolean) {
    if (enabled && ['code_execution', 'mcp'].includes(key) && !confirm(`Enable ${key.replace('_', ' ')} for this studio? Workflows still require an agent permission and a visible approval, but executable code can access data available to your Windows account.`)) return;
    await update({ capabilities: { ...settings.capabilities, [key]: enabled } });
  }

  async function installPython() {
    setError(undefined); setMessage(undefined);
    try {
      setPython(await api.post<PythonRuntime>('/api/runtime/python/install', { acknowledged: pythonConsent }));
      setMessage('Python setup started. You can leave this page; progress stays visible here.');
      for (let attempt = 0; attempt < 900; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        const state = await api.get<PythonRuntime>('/api/runtime/python'); setPython(state);
        if (['ready', 'ready_restart', 'failed'].includes(state.status)) { await reload(); break; }
      }
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Python setup could not start.'); }
  }

  async function savePythonPath() {
    try {
      setPython(await api.put<PythonRuntime>('/api/runtime/python/path', { path: pythonPath }));
      setMessage('Python path verified and saved.'); setError(undefined); await reload();
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'That Python path could not be verified.'); }
  }

  async function saveMcpServer() {
    try {
      const saved = await api.put<MCPServer>('/api/mcp/servers', {
        ...mcpForm, args: mcpForm.args.split('\n').map((item) => item.trim()).filter(Boolean), enabled: true,
      });
      setMcpServers((current) => [...current.filter((item) => item.id !== saved.id), saved]);
      setMcpForm({ name: '', command: '', args: '', warning_acknowledged: false });
      setMessage('Local MCP server saved. Its tools remain approval-gated.'); setError(undefined); await reload();
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'The MCP server could not be saved.'); }
  }

  async function removeMcpServer(id: string) {
    if (!confirm('Remove this MCP server configuration?')) return;
    try { await api.delete(`/api/mcp/servers/${id}`); setMcpServers((items) => items.filter((item) => item.id !== id)); await reload(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'The MCP server could not be removed.'); }
  }

  return <>
    <Header eyebrow="Your control" title="Settings" subtitle="Clear choices for privacy, providers, integrations, storage, and permissions." />
    {message && <Notice kind="success">{message}</Notice>}
    {error && <Notice kind="error">{error}</Notice>}

    <section className="settings-section cloud-settings">
      <div className="section-title"><div><h2>Optional free cloud model</h2><p>Use Gemini only when you explicitly connect it.</p></div>{gemini?.configured && <span className="pill green">Connected</span>}</div>
      <div className="setting-row"><span className="setting-icon gemini"><Cloud /></span><span><strong>Gemini 3.5 Flash</strong><small>Google offers a free tier; your actual rate limit is shown in Google AI Studio. Requests sent to this provider leave your computer, and free-tier data may be used by Google to improve its products.</small></span></div>
      {!gemini?.configured ? <div className="cloud-connect-box">
        <ol><li>Open Google AI Studio and sign in.</li><li>Choose <strong>Get API key</strong>, then create or copy a key.</li><li>Paste it below. We verify it once and encrypt it with Windows protection.</li></ol>
        <div className="button-row left"><a className="secondary link-button" href={gemini?.ai_studio_url || 'https://aistudio.google.com/app/apikey'} target="_blank" rel="noreferrer">Open AI Studio <ExternalLink size={15} /></a><a className="text-button" href={gemini?.quota_url || 'https://aistudio.google.com/usage'} target="_blank" rel="noreferrer">View live quota</a></div>
        <label className="key-field"><span><KeyRound size={15} /> Google API key</span><input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="Paste your AI Studio key" autoComplete="off" /></label>
        <button className="primary" disabled={connecting || apiKey.trim().length < 20 || settings.offline_mode} onClick={() => void connectGemini()}>{connecting ? 'Verifying…' : 'Verify and connect'}</button>
        {settings.offline_mode && <small className="inline-help">Turn off Offline mode below before connecting a cloud provider.</small>}
      </div> : <div className="connected-provider"><span><ShieldCheck size={18} /><span><strong>Ready to use</strong><small>The key is never returned to the interface or included in exports.</small></span></span><button className="secondary danger" disabled={connecting} onClick={() => void disconnectGemini()}><Unplug size={15} /> Disconnect</button></div>}
    </section>

    <section className="settings-section email-settings">
      <div className="section-title"><div><h2>Email for workflows</h2><p>Connect the account messages should be sent from. Each Send email node chooses its recipient.</p></div>{email?.configured && <span className="pill green">Saved securely</span>}</div>
      <div className="setting-row"><span className="setting-icon email"><Mail /></span><span><strong>Sending account</strong><small>Email always pauses for approval and shows the recipient, subject, and message before anything is sent.</small></span></div>
      <div className="integration-form">
        <label>Email provider<select value={emailForm.provider} onChange={(event) => chooseEmailProvider(event.target.value as EmailConfig['provider'])}><option value="gmail">Gmail</option><option value="outlook">Outlook / Microsoft 365</option><option value="yahoo">Yahoo Mail</option><option value="custom">Custom SMTP</option></select></label>
        <div className="split-fields"><label>From email<input type="email" value={emailForm.sender_email} onChange={(event) => setEmailForm({ ...emailForm, sender_email: event.target.value, username: emailForm.username || event.target.value })} placeholder="you@example.com" /></label><label>Display name<input value={emailForm.sender_name} onChange={(event) => setEmailForm({ ...emailForm, sender_name: event.target.value })} placeholder="Local Agent Studio" /></label></div>
        <div className="split-fields"><label>Login email / username<input value={emailForm.username} onChange={(event) => setEmailForm({ ...emailForm, username: event.target.value })} placeholder="Usually the same email" /></label><label>{email?.password_saved ? 'New password or app password (optional)' : 'Password or app password'}<input type="password" value={emailForm.password} onChange={(event) => setEmailForm({ ...emailForm, password: event.target.value })} autoComplete="new-password" placeholder={email?.password_saved ? 'Leave blank to keep the saved password' : 'Stored encrypted on this PC'} /></label></div>
        {emailForm.provider === 'custom' && <div className="custom-smtp-grid"><label>SMTP server<input value={emailForm.host} onChange={(event) => setEmailForm({ ...emailForm, host: event.target.value })} placeholder="smtp.example.com" /></label><label>Port<input type="number" min="1" max="65535" value={emailForm.port} onChange={(event) => setEmailForm({ ...emailForm, port: Number(event.target.value) })} /></label><label>Security<select value={emailForm.security} onChange={(event) => setEmailForm({ ...emailForm, security: event.target.value as EmailConfig['security'] })}><option value="starttls">STARTTLS</option><option value="ssl">SSL/TLS</option></select></label></div>}
        <Notice><span>{emailForm.provider === 'gmail' ? <>Gmail normally requires 2-Step Verification and an <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer">App Password</a>.</> : emailForm.provider === 'outlook' ? 'Microsoft accounts may require SMTP AUTH or an app password enabled by the account administrator.' : emailForm.provider === 'yahoo' ? 'Yahoo normally requires an app password rather than the regular account password.' : 'Use the SMTP server, port, security mode, and credentials supplied by the email provider.'}</span></Notice>
        <div className="button-row left"><button className="primary" disabled={emailBusy || !emailForm.sender_email.trim() || !emailForm.username.trim() || (!emailForm.password && !email?.password_saved)} onClick={() => void saveEmail()}>{emailBusy ? 'Working…' : 'Save sending account'}</button>{email?.configured && <button className="secondary danger" disabled={emailBusy} onClick={() => void disconnectEmail()}><Unplug size={15} /> Remove</button>}</div>
        {email?.configured && <div className="email-test-row"><label>Send a test to<input type="email" value={testRecipient} onChange={(event) => setTestRecipient(event.target.value)} placeholder="recipient@example.com" /></label><button className="secondary" disabled={emailBusy || !testRecipient.includes('@')} onClick={() => void testEmail()}><Send size={15} /> Send test</button></div>}
      </div>
    </section>

    <section className="settings-section capability-settings">
      <div className="section-title"><div><h2>Studio capabilities</h2><p>Master switches override every agent. Turning a capability off stops it in the backend, not only in the interface.</p></div><span className="pill green">Secure by default</span></div>
      {([
        ['attachments', 'Files and images', 'Allow run-time attachments and approved local paths.'],
        ['file_access', 'Approved workspace files', 'Allow reading and approval-gated writing only inside the studio workspace.'],
        ['web_access', 'Network and web access', 'Allow agent-authorized calls only to HTTPS domains on your allowlist.'],
        ['code_execution', 'Python code execution', 'Developer Mode. Arbitrary Python has your Windows account privileges and always needs approval.'],
        ['mcp', 'Local MCP servers', 'Developer Mode. Stdio MCP servers can run code and always need approval.'],
      ] as const).map(([key, title, description]) => <div className="setting-row" key={key}><span className="setting-icon">{key === 'code_execution' ? <Code2 /> : key === 'mcp' || key === 'web_access' ? <Network /> : <ShieldCheck />}</span><span><strong>{title}</strong><small>{description}</small></span><label className="switch"><input type="checkbox" checked={settings.capabilities[key]} onChange={(event) => void updateCapability(key, event.target.checked)} /><span /></label></div>)}
    </section>

    <section className="settings-section developer-settings">
      <div className="section-title"><div><h2>Python functions</h2><p>Python is optional and is never silently installed.</p></div>{python?.available && <span className="pill green">{python.version}</span>}</div>
      {python?.available ? <div className="connected-provider"><span><Code2 size={18} /><span><strong>Python ready</strong><small>{python.path}</small></span></span><button className="secondary" onClick={() => void loadDeveloperRuntimes()}>Check again</button></div> : <div className="integration-form">
        <Notice kind="error"><span><strong>Python was not found.</strong> Python functions cannot be added until a Python 3 interpreter is verified.</span></Notice>
        <label className="check-row"><input type="checkbox" checked={pythonConsent} onChange={(event) => setPythonConsent(event.target.checked)} /> Install Python’s official Windows Install Manager and current Python 3 runtime for my user account.</label>
        <div className="button-row left"><button className="primary" disabled={!pythonConsent || settings.offline_mode || ['installing_manager', 'installing_runtime'].includes(python?.status ?? '')} onClick={() => void installPython()}>{python?.status?.startsWith('installing') ? `${Math.round((python.progress ?? 0) * 100)}% · Installing…` : 'Install Python'}</button><a className="secondary link-button" href="https://www.python.org/downloads/" target="_blank" rel="noreferrer">Official Python page <ExternalLink size={14} /></a></div>
        {python?.detail && <small>{python.detail}{python.error ? ` ${python.error}` : ''}</small>}
        <div className="split-fields"><label>Already installed? Python executable path<input value={pythonPath} onChange={(event) => setPythonPath(event.target.value)} placeholder="C:\\Path\\To\\Python\\python.exe" /></label><button className="secondary align-end" disabled={!pythonPath.trim()} onClick={() => void savePythonPath()}>Verify path</button></div>
      </div>}
      <Notice><span>Python snippets are not a security sandbox. Before every run, Local Agent Studio shows the exact code and pauses for approval; use only code you understand.</span></Notice>
    </section>

    <section className="settings-section developer-settings">
      <div className="section-title"><div><h2>Local MCP servers</h2><p>V1 supports local stdio servers only; it does not expose MCP over the network.</p></div>{mcpServers.length > 0 && <span className="pill green">{mcpServers.length} connected</span>}</div>
      {!settings.capabilities.mcp ? <Notice kind="error">Enable Local MCP servers in Studio capabilities before adding one.</Notice> : <div className="integration-form">
        {mcpServers.map((server) => <div className="connected-provider" key={server.id}><span><Network size={18} /><span><strong>{server.name}</strong><small>{server.command} · stdio</small></span></span><button className="icon-button danger" aria-label={`Remove ${server.name}`} onClick={() => void removeMcpServer(server.id)}><Trash2 size={15} /></button></div>)}
        <div className="split-fields"><label>Server name<input value={mcpForm.name} onChange={(event) => setMcpForm({ ...mcpForm, name: event.target.value })} placeholder="My local tools" /></label><label>Executable path<input value={mcpForm.command} onChange={(event) => setMcpForm({ ...mcpForm, command: event.target.value })} placeholder="Full path to the trusted executable" /></label></div>
        <label>Arguments, one per line<textarea rows={3} value={mcpForm.args} onChange={(event) => setMcpForm({ ...mcpForm, args: event.target.value })} placeholder="--directory\nC:\\approved-folder" /></label>
        <label className="check-row"><input type="checkbox" checked={mcpForm.warning_acknowledged} onChange={(event) => setMcpForm({ ...mcpForm, warning_acknowledged: event.target.checked })} /> I trust this server’s publisher and understand it runs with my Windows account permissions.</label>
        <button className="primary" disabled={!mcpForm.name.trim() || !mcpForm.command.trim() || !mcpForm.warning_acknowledged} onClick={() => void saveMcpServer()}><Plus size={15} /> Add trusted server</button>
      </div>}
    </section>

    <section className="settings-section"><h2>Privacy</h2><div className="setting-row"><span className="setting-icon"><LockKeyhole /></span><span><strong>Offline mode</strong><small>Blocks model downloads and cloud-model calls. External tools such as HTTP and email still require separate approval.</small></span><label className="switch"><input type="checkbox" checked={settings.offline_mode} onChange={(event) => void update({ offline_mode: event.target.checked })} /><span /></label></div><div className="setting-row"><span className="setting-icon"><ShieldCheck /></span><span><strong>Local by default</strong><small>llama.cpp, Ollama, and LM Studio stay on 127.0.0.1. Gemini is contacted only for agents you assign to it.</small></span><span className="pill green">Protected</span></div></section>
    <section className="settings-section"><h2>Storage and approved folders</h2><div className="setting-row"><span className="setting-icon"><Folder /></span><span><strong>Managed models</strong><small>{settings.models_dir}</small></span></div><div className="setting-row"><span className="setting-icon"><Folder /></span><span><strong>Approved workspace</strong><small>{settings.workspace_dir}</small></span></div><div className="setting-row"><span className="setting-icon"><Folder /></span><span><strong>Additional folders</strong><small>One full folder path per line. Workflows may read only the workspace and folders you explicitly approve here.</small><textarea rows={3} value={approvedFolders} onChange={(event) => setApprovedFolders(event.target.value)} placeholder="C:\\Documents\\Reports" /></span><button className="secondary" onClick={() => void update({ approved_folders: approvedFolders.split('\n').map((item) => item.trim()).filter(Boolean) } as Partial<Settings>)}>Approve folders</button></div></section>
    <section className="settings-section"><h2>Network tool allowlist</h2><div className="setting-row"><span className="setting-icon"><ShieldCheck /></span><span><strong>Approved HTTPS domains</strong><small>HTTP tools cannot contact any other domain. Separate multiple domains with commas.</small><input value={domains} onChange={(event) => setDomains(event.target.value)} placeholder="api.example.com, data.example.org" /></span><button className="secondary" onClick={() => void update({ approved_domains: domains.split(',').map((item) => item.trim()).filter(Boolean) } as Partial<Settings>)}>Save domains</button></div></section>
    <section className="settings-section"><h2>Optional local runtimes</h2><div className="setting-row"><span className="runtime-logo ollama">O</span><span><strong>Ollama</strong><small>MIT-licensed external runtime. Install it if you want its model library and scheduler.</small></span><a className="secondary link-button" href="https://ollama.com/download/windows" target="_blank" rel="noreferrer">Official installer <ExternalLink size={15} /></a></div><div className="setting-row"><span className="runtime-logo lm_studio">L</span><span><strong>LM Studio</strong><small>Proprietary external application. It is never bundled or redistributed here.</small></span><a className="secondary link-button" href="https://lmstudio.ai/download" target="_blank" rel="noreferrer">Official site <ExternalLink size={15} /></a></div></section>
    <section className="settings-section"><h2>First-run experience</h2><div className="setting-row"><span className="setting-icon"><RotateCcw /></span><span><strong>Show setup guide again</strong><small>Does not delete agents, workflows, models, or run history. If hardware detection fails, the guide offers conservative defaults instead of getting stuck.</small></span><button className="secondary" onClick={() => void update({ onboarding_complete: false })}>Restart guide</button></div></section>
    <section className="license-box"><strong>Local Agent Studio 0.5.1</strong><p>Apache-2.0 licensed and provided “as is.” No software can guarantee freedom from vulnerabilities or data loss. Keep independent backups, review approvals and generated output, and use external providers, code, MCP servers, and email at your own risk to the maximum extent permitted by law. Model weights and external services retain their own terms. See DISCLAIMER.md in the project repository.</p></section>
  </>;
}
