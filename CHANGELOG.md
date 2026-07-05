# Changelog

## 0.5.2 - 2026-07-04

- Added an explicit per-node choice for Send Email: ask every time or send
  automatically for that workflow node. Other consequential tools remain
  approval-gated.
- Replaced raw Gmail SMTP authentication failures with App Password setup
  guidance and normalized spaces in pasted Gmail App Passwords.
- Made each agent's provider and model visible in workflow agent selectors so
  cloud and local agents can be intentionally combined.
- Added executed scenario coverage for Gemini-to-Ollama handoffs, manual email
  approval, automatic email sending, Gmail authentication guidance, and the
  non-bypassability of file-write approvals.
- Expanded the packaged UI audit to configure Send Email approval behavior and
  verify a cross-provider agent appears in the workflow editor.

## 0.5.1 - 2026-07-04

- Kept all four first-run provider choices visible even when one provider probe
  fails or returns incomplete data.
- Added direct packaged-UI coverage for the Gemini setup guide, API-key field,
  and Google AI Studio link.
- Treated successful Ollama or LM Studio model discovery as stronger evidence
  than a stale health probe, so usable local models are no longer blocked.
- Distinguished an installed local app with its server stopped from an app that
  is not installed.
- Isolated provider and model discovery failures so one integration cannot hide
  the other providers or their models.

## 0.5.0 - 2026-07-04

- Added studio-wide master controls and narrower per-agent permissions for
  attachments, workspace files, network access, Python, and MCP.
- Added run-time document and image uploads plus approved local-path inputs,
  with bounded sizes and redacted image payloads in run inspection.
- Added multimodal image delivery for Gemini and compatible local vision APIs.
- Added opt-in Python Developer Mode with detection, verified custom paths,
  one-click official Windows installation, hard time/output bounds, and
  approval-bound execution.
- Added opt-in local stdio MCP server configuration using the stable official
  Python SDK, absolute executable paths, explicit trust acknowledgement, and
  approval-bound calls.
- Added a plain-language disclaimer and expanded the threat model and user
  guide for executable extensions, backups, and external data transfer.
- Replaced the fragile Electron audit with a deterministic, timeout-bounded
  packaged-app test covering onboarding, agents, permissions, attachments,
  workflow editing, functions, runs, resources, and settings.
- Switched the bundled backend from self-extracting one-file packaging to a
  fast-start directory bundle to eliminate repeated extraction delays.

## 0.4.0 - 2026-07-04

- Added encrypted Gmail, Outlook, Yahoo, and custom SMTP configuration with a
  real test-send flow and approval-bound email workflow execution.
- Added native Word document and Excel workbook reading, creation, and search
  tools with workspace confinement and spreadsheet formula-injection guards.
- Added encrypted Markdown, text, JSON, and YAML skill files for individual
  agents.
- Added workflow deletion, editable workflow details, and visual router rules.
- Bound approvals to the exact node, tool, and arguments presented to the user.
- Replaced full-app run polling with targeted updates and added database indexes
  for faster active-run checks.
- Prevented first-run hardware detection from leaving the setup guide stuck and
  added a conservative fallback path.
- Unified the application, tray, executable, and installer logo asset.

## 0.3.0 - 2026-07-03

- Added the opt-in Gemini 3.5 Flash provider with guided key verification,
  encrypted credential storage, and Offline-mode enforcement.
- Required an explicit provider choice and one runnable model during setup.
- Added one-click Qwen 2.5 0.5B starter installation for Ollama and LM Studio.
- Unified the in-app, tray, executable, and installer icon.
- Added a consistent indigo-and-teal visual theme and a clearer first-run flow.
- Added live per-node workflow progress, Stop run, and clean cancellation.
- Added meaningful Approval, Function, Router, and Review node configuration.
- Added beginner documentation, GitHub issue forms, CI, and security guidance.

## 0.2.0

- Added typed curated-tool arguments with `$input` piping.
- Added a publisher-hosted 491 MB Qwen quick-start model option.
- Reduced default context and output bounds for responsive 16 GB operation.

## 0.1.1

- Fixed the packaged Electron preload bridge so the renderer can reach the
  bundled authenticated backend.
