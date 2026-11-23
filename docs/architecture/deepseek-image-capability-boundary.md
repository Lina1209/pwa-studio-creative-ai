# DeepSeek image capability boundary

**Decision:** PWA Studio keeps DeepSeek as its only AI provider. DeepSeek is used for text generation and image understanding (vision input). It is not registered as an image-generation provider.

## Verified API capability

The current official DeepSeek model catalogue exposes model input modalities separately from output modalities. The current API model output modality is `text`; the Vision guide describes images as inputs to user messages so the model can analyze or describe them. This is not image synthesis and does not return a generated image asset.

Official references:
- [DeepSeek model catalogue](https://api-docs.deepseek.com/api/list-models/) — model metadata includes `input_modalities` and `output_modalities`.
- [DeepSeek Vision guide](https://api-docs.deepseek.com/guides/vision/) — image input for vision analysis.
- [DeepSeek Responses API](https://api-docs.deepseek.com/api/create-response/) — `input_image` is an input content part.

## Product and runtime behavior

- DeepSeek remains the only configured AI provider for chat, Prompt Studio, and vision understanding.
- `IMAGE_GENERATION_PROVIDER=deepseek` is rejected during settings validation. This prevents an input-only vision capability from being mistaken for image synthesis.
- The health endpoint reports `image_generation_configured=false` and `image_generation_status=unavailable_no_registered_provider` until an actual output-capable adapter is implemented and registered.
- The image worker protocol, durable provider-operation journal, cost admission, private storage, and result retrieval remain provider-neutral foundations. They do not imply that an image provider exists.
- No alternative provider is silently selected, no fallback is allowed, and no paid provider API is called.
- Generation job, worker-ready, and worker-runtime flags remain disabled.

## Reconsideration gate

Revisit only if DeepSeek officially adds an image output modality and documents:
1. generated image output format and retrieval contract;
2. stable idempotency and operation lookup semantics;
3. provider request IDs and terminal/ambiguous failure semantics;
4. usage and cost reporting suitable for preflight budget controls;
5. content safety behavior and commercial-use terms.

Until then, do not claim that image generation is available through DeepSeek. The UI should clearly distinguish **image understanding** from **image creation**.
