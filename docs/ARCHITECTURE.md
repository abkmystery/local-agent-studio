# Architecture

```text
Electron main process
  ├─ sandboxed React renderer
  ├─ random loopback port + launch token
  └─ bundled Python service
       ├─ SQLite + AES-GCM/DPAPI
       ├─ provider manager
       │    ├─ managed llama.cpp process
       │    ├─ Ollama native API
       │    ├─ LM Studio OpenAI-compatible API
       │    └─ opt-in Gemini Interactions API
       ├─ workflow engine + scheduler
       ├─ approval-enforcing tool registry
       │    ├─ text, Word, and Excel workspace tools
       │    ├─ allowlisted HTTP and encrypted SMTP integration
       │    └─ typed transformations
       └─ resource, download, benchmark, and agentpack services
```

## Provider boundary

`InferenceProvider` normalizes status, models, chat, tool calls, structured
output, usage, unload, and shutdown. Local providers are the privacy-first
default; Gemini is the single opt-in cloud provider in this release.

The built-in llama.cpp provider owns its process and only loads GGUF files from
the managed model directory. Ollama uses its native API for accurate token
usage and model inventory. LM Studio uses its published local compatibility
endpoint and remains an external installation.

The Gemini adapter uses the official Interactions API with `store: false`.
Credentials are decrypted only in the backend process. Offline mode rejects
cloud inference before a request is sent.

## Workflow format

`WorkflowSpec 1.0` is a provider-neutral directed acyclic graph. Free-form
cycles are rejected; bounded revision behavior is represented by a Review node
with a hard iteration cap. Topological levels are eligible for concurrent
execution, while a provider semaphore serializes local model calls when memory
capacity is unknown.

Supported nodes are Input, Agent, Function, Parallel, Router, Approval, Review,
and Output. Router edges are deactivated deterministically based on declared
contains-rules. Execution state is checkpointed after every level.

Consequential function approvals are cryptographically stored with run state
and logically bound to one node, tool identifier, and normalized argument set.
The engine rechecks that binding before execution.

## Agent skill files

Skill attachments are UTF-8 Markdown, text, JSON, or YAML records stored in
SQLite with encrypted content and searchable metadata. At inference time, a
bounded excerpt is appended only to that agent's system context. Files are
limited by count and size so attachments cannot silently consume the complete
model context.

## Capability and executable-extension boundary

The studio stores master switches for attachments, workspace files, network
access, Python, and MCP. Agent configuration can narrow those permissions. The
workflow engine checks both layers before privileged execution and requires a
named agent for network, Python, or MCP functions.

Run-time documents are extracted locally and appended to encrypted run input.
Image attachments remain encrypted inside run state, are removed from public
run responses, and are normalized into Gemini, Ollama, or OpenAI-compatible
multimodal message formats.

Python is an external, user-consented runtime rather than the frozen backend's
interpreter. Snippets run without a command shell, with bounded time and output,
after exact-code approval. MCP uses the stable official Python SDK and local
stdio transport only. Neither boundary is an operating-system sandbox.

## Portable packages

`.agentpack` is a ZIP containing `manifest.json`, `agents.json`, and
`workflow.json`. Export removes timestamps, secrets, API-key-like properties,
local paths, run history, and model binaries. Import assigns fresh identifiers
and rewrites agent references.

## Background operation

Closing the window hides it to the tray. The local service and interval
scheduler remain alive for that Windows login session. This is not a Windows
service and does not run before login. Public internet webhooks and multi-PC
execution are intentionally out of scope.
