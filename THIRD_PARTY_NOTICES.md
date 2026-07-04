# Third-party notices

This project is Apache-2.0 licensed. Release builds include or integrate with
third-party components under their own terms.

- **llama.cpp** — MIT License. Copyright the ggml authors. The release pipeline
  may bundle official llama.cpp binaries; model weights are never bundled by
  default.
- **Ollama** — MIT License. Ollama is an optional external runtime. The app may
  direct users to Ollama's official installer but does not require it.
- **LM Studio** — proprietary desktop software from Element Labs, Inc. LM
  Studio is not redistributed. Integration occurs only through its published
  local API when users have installed it independently.
- **Electron, React, React Flow, FastAPI, Pydantic, HTTPX, psutil, cryptography,
  the official Model Context Protocol Python SDK, python-docx, openpyxl, lxml,
  and PyInstaller** — see the generated `sbom-python.json` and
  `sbom-javascript.json` release artifacts for exact versions and licenses.

Model weights have licenses independent of their runtime. Local Agent Studio
shows model-source and license metadata and requires acknowledgement where
applicable. Users remain responsible for complying with each model license.
