# Local Agent Studio user guide

This guide assumes no AI-development experience.

## 1. Complete first-run setup

The setup wizard checks the computer without uploading hardware information.

1. Review the plain-language hardware summary.
2. Choose one provider. **Gemini 3.5 Flash** is the no-model-download cloud
   route; **Built-in llama.cpp** is the simplest private route.
3. For llama.cpp, Ollama, or LM Studio, choose one model. **Qwen 2.5 0.5B Quick
   Start** is the smallest default and can be installed from the wizard.
4. Leave the app open while the runtime and model download.
5. Select **Create my studio** after the engine and model both show ready.

The initial download needs internet access. Local inference works offline after
the runtime and model are installed. Gemini always needs internet access and
sends prompts for Gemini agents to Google.

### Gemini setup

1. Select **Connect free-tier Gemini**.
2. Open the provided Google AI Studio link and sign in.
3. Create/copy an API key, paste it into the wizard, and select **Verify and
   connect**. The app encrypts the verified key and never displays it again.

Google controls the live free-tier quota, so use the wizard's **View your live
usage** link rather than relying on a fixed requests-per-day number.

## 2. Run the sample workflow

1. Open **Workflows** in the left sidebar.
2. Select **Research then write**.
3. Enter a small task, such as `Turn these notes into three clear bullets`.
4. Select **Run & watch**.
5. The app opens **Runs** and shows each step as it changes.

The sample does not browse the internet. Its Researcher organizes the material
provided in the task; connect an approved HTTP tool when fresh web data is
needed.

## 3. Understand run progress

- **Pending:** waiting for an earlier node.
- **Running:** currently processing locally.
- **Waiting approval:** paused until a person approves or rejects it.
- **Completed:** result is available under **Show result**.
- **Skipped:** a router or inactive branch did not select this node.
- **Failed:** the node stopped with the displayed error.
- **Cancelled:** the user stopped or rejected the run.

Select **Stop run** at any time. The current local request is cancelled and
later nodes are skipped.

### Attach a file, image, or approved local path

The workflow composer accepts up to five `.txt`, `.md`, `.json`, `.csv`,
`.yaml`, `.docx`, `.xlsx`, `.png`, `.jpg`, `.webp`, or `.gif` attachments, up
to 12 MB total. Select the paperclip for a file picker. To use an existing file,
enter one full path per line; paths must remain inside the approved workspace
shown in Settings. Documents are read locally. Images require a vision-capable
model; Gemini supports inline images, while local behavior depends on the
selected Ollama or LM Studio model.

## 4. Create an agent

Open **Agents → New agent** and provide:

- a short name;
- one job description;
- a local model or the explicitly connected Gemini model;
- direct instructions;
- a creativity value;
- a working context and maximum answer length.

Use 4,096 context tokens and 128 answer tokens until a real task proves that it
needs more. Bigger numbers consume more memory and time.

### Give one agent reusable skills

In the agent editor, select **Add skill files** and choose up to six UTF-8
Markdown, text, JSON, or YAML files. These can contain a writing style, review
checklist, domain rules, or a repeatable procedure. They are encrypted on this
computer and are supplied only to that agent. Keep them concise: each file is
limited to 20 KB and the inference context uses a bounded excerpt.

### Limit what an agent may do

Each agent has permissions for attachments, workspace files, network access,
Python, and MCP. A studio-wide switch in Settings can disable a capability for
every agent. An agent switch cannot override a disabled studio switch. Network,
Python, and MCP Function nodes must also identify the agent whose permissions
authorize the action.

For Gemini agents, enabling web access at both levels also enables Gemini's
grounded Google Search tool. Prompts and search activity then leave the
computer under Google's terms. Local agents do not silently gain a search
service; use an explicit allowlisted HTTP Function or a trusted MCP search tool.

## 5. Add meaningful workflow nodes

Select a canvas node to open its Inspector.

### Approval

Write the decision the person must make, add review instructions, choose whether
to show incoming data, and optionally allow a written note. Rejection stops the
run safely.

### Function

Choose a curated function and fill each displayed argument. Enter `$input` when
the argument should use the previous node's result. File writes, email, and
mutating HTTP requests cannot proceed without approval.

Useful starter functions include:

- **Read file or document:** reads text, `.docx`, or `.xlsx` from the approved
  workspace.
- **Create Word document:** creates a real `.docx` from a title and content.
- **Create Excel workbook:** creates a real `.xlsx` from JSON rows, arrays, or
  CSV. Potential spreadsheet formulas are stored as text by default.
- **Send email:** sends through the account configured in Settings after the
  Runs page shows the recipient, subject, and body for approval.

Paths such as `reports/summary.docx` are relative to the approved workspace
shown in **Settings → Storage**. The app does not write elsewhere.

### Python functions (Developer Mode)

Open **Settings → Studio capabilities** and enable Python only if the workflow
needs custom code. If Python 3 is missing, the app offers an explicit one-click
installation through Python's official Windows Install Manager. You may instead
provide the full path to an existing `python.exe` for verification.

The Function editor does not offer Python until the runtime and master switch
are ready. Select an authorizing agent and provide code that reads JSON from
standard input and writes its result to standard output. Every run shows the
exact code and pauses for approval. Time and output are bounded, but this is not
a security sandbox: approved Python has the current Windows user's privileges.

### MCP tools (Developer Mode)

V1 supports trusted local stdio MCP servers. Enable MCP in Settings, provide a
full executable path and one argument per line, and acknowledge the publisher
trust warning. Then select **MCP server tool** in a Function node, identify the
authorizing agent, and enter the server, tool, and JSON arguments. Each call
pauses for approval. Do not add an MCP server whose source or publisher you do
not trust.

### Review

Choose a writer, reviewer, and maximum number of revision rounds. Keep the limit
small because every round invokes the model twice.

## 6. Improve speed

1. Test one agent before building a multi-agent flow.
2. Use the 0.5B or 3B model for iteration.
3. Keep context at 4,096.
4. Set maximum answer tokens between 128 and 256.
5. Remember that the first run includes model loading.
6. Check **Resources** for RAM usage and benchmark speed.

## 7. Data locations

Application data is stored under `%APPDATA%\local-agent-studio`. Models are kept
when the application is upgraded. The uninstaller should be used when removing
the desktop application; delete application data only when its prompts, history,
and downloaded models are no longer needed.

## 8. Connect email safely

1. Open **Settings → Email for workflows**.
2. Choose Gmail, Outlook / Microsoft 365, Yahoo, or Custom SMTP.
3. Enter the sending address, login username, and password or provider app
   password. The password is encrypted and never displayed again.
4. Select **Save sending account**.
5. Enter an address under **Send a test to** and select **Send test**.
6. Add a Function node to a workflow and choose **Send email**. Enter the
   recipient and subject; use `$input` as the body when the prior node produces
   the message.

Gmail and Yahoo usually require an app password. Microsoft 365 administrators
may need to enable authenticated SMTP. Local Agent Studio does not weaken or
bypass provider security settings.

## 9. If the setup guide cannot read the PC

The hardware check now has a short upper bound. If Windows hardware reporting
fails, the guide shows the error and offers **Continue with safe defaults** or
**Try hardware check again**. Restarting the guide does not remove models,
agents, workflows, or history.

## 10. Backups and responsibility

Keep an independent backup of important prompts, workflows, files, credentials,
and results. Local-first software can still lose data through disk failure,
upgrades, user action, or defects. Review AI output and every approval before
relying on it. Cloud models, email, HTTP, Python, and MCP cross additional trust
boundaries; see `DISCLAIMER.md` and `SECURITY.md` before using them with
sensitive or regulated information.
