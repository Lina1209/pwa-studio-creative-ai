# Vision consent and data-flow specification

Status: implementation specification for the integration branch. This is not legal approval to enable Vision.

## User-facing disclosure (Russian draft)

> **Анализ изображения с помощью DeepSeek**
>
> Если вы продолжите, выбранное изображение и ваш текстовый запрос будут отправлены с сервера PWA Studio в DeepSeek для анализа. DeepSeek — внешний поставщик AI-модели. Обработка у провайдера регулируется его применимыми условиями; PWA Studio не может обещать, что провайдер не сохранит полученные данные.
>
> Не отправляйте конфиденциальные материалы, персональные данные, изображения других людей без необходимых прав и разрешений, а также изображения детей. Перед отправкой убедитесь, что у вас есть право использовать изображение.
>
> PWA Studio обрабатывает изображение в памяти, удаляет доступные метаданные EXIF/GPS и не сохраняет исходный файл в своей медиатеке или базе данных. Это не означает автоматического удаления данных у DeepSeek.
>
> [Открыть Политику конфиденциальности PWA Studio] · [Открыть Политику конфиденциальности DeepSeek]

Checkbox (unchecked by default):

> Я прочитал(а) уведомление и Политику конфиденциальности PWA Studio. Я отдельно соглашаюсь отправить выбранное изображение и мой запрос внешнему поставщику DeepSeek для анализа. Я понимаю, что обработка у DeepSeek регулируется его применимыми условиями и политикой, и что PWA Studio не контролирует сроки хранения данных провайдером.

Button: **Отправить изображение в DeepSeek и проанализировать**

The existing short checkbox copy in the UI is temporary, not final consent language. Replace it only after legal review and ensure both policy links work.

## Data-flow boundary

1. User chooses one image and sees a local preview.
2. Browser keeps the File and temporary object URL in memory only.
3. User explicitly checks the unchecked consent control and presses Analyze.
4. Browser posts the bounded data URL and prompt to the authenticated PWA Studio backend over HTTPS.
5. Backend performs distributed admission before expensive image decoding.
6. Backend validates bytes, actual format, dimensions and file size; rejects animation and invalid formats; normalizes pixels and strips metadata.
7. Backend reserves estimated Vision cost in the shared global/provider ledger.
8. Only then may the server call DeepSeek Flash. No browser-supplied provider ID or external URL is accepted.
9. Backend settles using provider-reported usage. Ambiguous outcomes remain unknown and are not automatically released or retried.
10. API returns analysis text only. Browser clears file selection, preview URL and consent after success; on sign-out/account change it clears local Vision state.

## Required implementation controls

- Consent must be explicit, specific, informed, freely given, recorded in a minimal audit record, and revocable for future requests where applicable.
- Consent must be tied to the exact current image and prompt. Changing either resets consent.
- Never pre-check consent or bundle it with general terms acceptance.
- Do not send image bytes before the user presses the explicit action.
- Do not put image bytes, data URLs, prompts, provider payloads, signed URLs, API keys or raw provider errors in logs, analytics, localStorage, IndexedDB, chat history or URLs.
- Do not claim PWA Studio can delete content from DeepSeek unless a verified API deletion mechanism and contract support that claim.
- Show provider identity and destination countries before consent once confirmed.
- If API-specific retention, location or model-improvement terms are unknown, keep the feature disabled.
- Maintain a separate versioned consent text and timestamp/version record; do not store the image itself as evidence of consent.
- Provide a clear route for withdrawal and privacy requests.
- Keep the feature flag off until all launch gates in the privacy notice are approved.

## Unresolved decisions — verify from contracts/configuration, do not guess

- DeepSeek API contracting entity and applicable API-specific terms.
- API processing and storage country/region; onward transfers and subprocessors.
- Provider retention period for API prompts/images and operational logs.
- Whether API inputs/outputs may be used for model improvement/training and available opt-out.
- Provider deletion/request process and its scope.
- Actual Render, Supabase, backup and CDN data locations.
- Whether user prompts/history are persisted, for how long, and whether users can delete/export them.
- Applicable Kazakhstan local storage, cross-border transfer, consent and notification requirements.
- Legal operator identity, contact address, privacy email, age threshold and complaint authority.

## Launch checklist

- [ ] Public privacy notice approved and linked from the app.
- [ ] Provider API terms and privacy/data-processing terms reviewed and archived.
- [ ] Country-by-country transfer map and Kazakhstan legal review completed.
- [ ] Consent text approved and versioned.
- [ ] Privacy request and withdrawal workflow tested.
- [ ] Retention/deletion schedule implemented and tested.
- [ ] Security/logging review completed.
- [ ] Explicit release approval obtained before setting VISION_INPUT_ENABLED=true.