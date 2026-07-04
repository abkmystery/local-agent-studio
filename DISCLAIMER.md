# Disclaimer and responsible-use notice

Local Agent Studio is early-stage software provided under the Apache License
2.0 on an **"AS IS"** basis, without warranties or conditions of any kind.
This notice explains product risks in plain language; it is not legal advice
and does not replace terms, a privacy policy, or review by qualified counsel.

## Back up important data

Software, hardware, storage devices, model runtimes, upgrades, user actions,
and third-party services can fail. Keep independent, tested backups of any
file, prompt, workflow, credential, or result that matters. Do not treat the
studio database or downloaded model directory as the only copy of important
information.

## Review actions and output

AI output can be incomplete, inaccurate, unsafe, or unsuitable for a specific
purpose. Review output before relying on it. Approval prompts reduce accidental
actions but do not guarantee that an approved file write, email, HTTP request,
Python snippet, or MCP call is correct or harmless.

## Understand data transfer

Local inference stays on the computer by default. Data leaves the computer
when a user chooses a cloud model or approves a network action such as email or
HTTP. External providers control their own retention, training, security,
availability, pricing, and terms. Do not send confidential, regulated, or
third-party data unless you have authority and have reviewed the provider.

## Executable extensions are powerful

Python snippets and local MCP servers are disabled by default. When enabled
and approved, they can act with the current Windows user's privileges. The
application's timeouts, output limits, no-shell invocation, absolute executable
paths, and approval checks reduce risk but are not a complete security sandbox.
Run only code and servers whose source and publisher you trust.

## Responsibility and limitation

To the maximum extent permitted by applicable law, users are responsible for
their configurations, credentials, backups, approvals, content, legal
compliance, and use of third-party models and services. The Apache-2.0 warranty
disclaimer and limitation-of-liability terms govern the open-source software.
Commercial distribution may require separate terms, privacy disclosures,
consumer-law review, and jurisdiction-specific advice.
