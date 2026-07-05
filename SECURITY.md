# Security model

## Trust boundaries

The Electron renderer is unprivileged: Node integration is disabled, context
is isolated, sandboxing is enabled, and navigation outside the packaged app is
blocked. A preload bridge provides only the randomly selected local API address
and its 256-bit per-launch authentication token.

The Python service binds to loopback and rejects requests without that token.
Ollama, LM Studio, and llama.cpp endpoints are contacted only on loopback.
Gemini is an explicit cloud boundary: it is contacted only by agents configured
for Gemini and is blocked by Offline mode.

## Data at rest

Instructions, run inputs, outputs, and resumable workflow state are encrypted
with AES-256-GCM. The random master key is protected for the current Windows
user with DPAPI. SQLite metadata that must be searchable remains unencrypted.
The optional Gemini API key is encrypted with the same protected key and is
never returned to the renderer or exported in an `.agentpack`.
SMTP passwords and attached agent skill-file contents use the same encryption
boundary. Neither is returned to the renderer after storage or included in an
`.agentpack` export.
Run-time image bytes are stored only in encrypted run state and are removed
from API responses; document text is extracted locally and becomes part of the
encrypted run input.

## Tools

- File paths must resolve beneath an approved workspace root.
- File writes always require an approval event.
- Word and Excel creation is confined to the approved workspace and always
  requires approval. Spreadsheet strings that could become formulas are escaped.
- HTTP is HTTPS-only; non-read methods require approval and redirects are off.
- Email is unavailable until SMTP is configured and asks for approval by
  default. A workflow author can explicitly mark only a Send Email node as
  automatic; the editor displays a warning, and that exception cannot bypass
  approval for file writes, Python, MCP, or mutating HTTP.
- Approval records are scoped to the exact workflow node, tool, and argument
  set shown to the user; one approval cannot authorize a sibling action.
- Studio-wide capability switches are enforced in the backend. Per-agent
  permissions can narrow, but never override, those switches.
- Python execution is disabled by default, requires an explicitly verified
  external Python 3 runtime, a named authorizing agent, and exact-code approval.
  It uses no shell, an isolated interpreter flag, a minimal environment, a
  temporary script, a 60-second hard ceiling, and bounded output. This is not
  an OS sandbox; approved Python still has the user's Windows privileges.
- MCP is disabled by default and supports local stdio only. Servers require an
  absolute executable path and explicit trust acknowledgement. Every tool call
  requires approval and results are bounded. A trusted MCP server still runs
  with the user's Windows privileges.

Approval is enforced in the backend, not in model prompts or UI-only logic.

## Downloads and updates

Automatic llama.cpp installation uses the official GitHub release API. The
installer refuses release assets without a published SHA-256 digest, verifies
the digest before extraction, checks for archive path traversal, and swaps the
runtime only after successful extraction.

GGUF downloads require explicit model-license acknowledgement and support an
optional pinned SHA-256. Production model catalogs must require hashes for
Automatic recommendations.

## Release requirements

- Generate and retain Python and JavaScript SBOMs.
- Review PyInstaller warnings and Electron dependency audit output.
- Sign `local-agent-backend.exe` and the final NSIS installer.
- Scan packaged artifacts with Windows Defender and a second malware scanner.
- Verify installation and upgrade on clean Windows 10 22H2 and Windows 11 VMs.
- Apply the NIST SSDF practices for security requirements, protected build
  infrastructure, secure production, vulnerability response, and dependency
  provenance.

Report vulnerabilities through this repository's **Security → Report a
vulnerability** form so the details remain private. If private reporting is not
available, open a public issue containing only a request for a private contact;
do not include exploit details, prompts, credentials, model files, logs, local
paths, or user databases.
