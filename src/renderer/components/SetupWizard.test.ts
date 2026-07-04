import { describe, expect, it } from 'vitest';
import type { ModelDescriptor, ProviderStatus } from '../types';
import { completeProviderChoices, providerIsReady } from './SetupWizard';

const localStatus = (id: string, available = false): ProviderStatus => ({
  id, name: id, kind: 'external', available, base_url: 'http://127.0.0.1',
  detail: '', license_name: 'test', redistributable: false,
});

describe('first-run provider choices', () => {
  it('always shows Gemini and all three local choices when detection is incomplete', () => {
    const choices = completeProviderChoices([
      localStatus('llama_cpp'), localStatus('ollama'), localStatus('lm_studio'),
    ]);
    expect(choices.map((provider) => provider.id)).toEqual(['gemini', 'llama_cpp', 'ollama', 'lm_studio']);
  });

  it('accepts successful local model discovery as stronger evidence than a stale health probe', () => {
    const model = {
      id: 'qwen', name: 'Qwen', provider_id: 'ollama', publisher: 'Local',
      license_name: 'Apache-2.0', capabilities: ['chat'], installed: true, loaded: false,
    } satisfies ModelDescriptor;
    expect(providerIsReady('ollama', [localStatus('ollama', false)], [model])).toBe(true);
    expect(providerIsReady('lm_studio', [localStatus('lm_studio', false)], [model])).toBe(false);
  });

  it('shows Gemini as ready after its key is configured even before status refresh completes', () => {
    expect(providerIsReady('gemini', [], [], true)).toBe(true);
  });
});
