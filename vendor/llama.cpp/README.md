# llama.cpp release payload

The release pipeline may place verified official `llama-server.exe` binaries
and their DLLs here before packaging. Executables are deliberately not committed
to source control.

At runtime the app can instead fetch an official Windows x64 CPU or Vulkan ZIP
from the llama.cpp GitHub release API. It requires the release asset's published
SHA-256 digest and safely extracts into the user's application-data directory.
