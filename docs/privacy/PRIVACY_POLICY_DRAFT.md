# PWA Studio Privacy Notice — working draft (NOT FOR PUBLICATION)

> **Status: draft only.** This file is an implementation and legal-review worksheet, not an approved privacy policy or legal opinion. Do not publish it or enable Vision until every bracketed field is resolved and qualified counsel has reviewed the complete data flow under the laws of every launch market. This draft deliberately does not promise provider retention, data residency, deletion, or security outcomes that have not been contractually and technically verified.

**Effective date:** [DATE — set only after approval]  
**Service operator / data controller:** [FULL LEGAL NAME OR INDIVIDUAL NAME, LEGAL FORM, REGISTRATION DETAILS IF APPLICABLE]  
**Contact for privacy requests:** [MONITORED PRIVACY EMAIL / POSTAL CONTACT]  
**Service address:** [LEGAL ADDRESS]  
**Applicable law and complaint authority:** [COUNSEL TO CONFIRM FOR EACH MARKET]

## 1. Who operates PWA Studio

PWA Studio is an independent AI-assisted creative studio operated by [OPERATOR]. The operator determines why and how personal data is processed through PWA Studio, subject to applicable law and the actual contracts with infrastructure and AI providers.

DeepSeek is an external AI model/API provider used for text assistance and, only if separately enabled, image understanding. DeepSeek does not operate PWA Studio. Its consumer-app privacy policy is not automatically the privacy policy for a developer's downstream application. The API-specific contract, data processing terms, service region, retention and subprocessors must be confirmed separately before launch.

## 2. Data we may process

The exact categories depend on features used and must be checked against the production configuration:
- Account and authentication data: [CONFIRM exact fields supplied by Supabase Auth, including email and identifiers].
- Creative inputs: text prompts, instructions, generated text and other content deliberately submitted.
- Uploaded media: images, video, audio or other files only when a feature accepts them. Each media feature needs its own disclosure, consent and retention rules.
- Generation and job metadata: job identifiers, status, timestamps, selected settings, ownership identifiers, result metadata and error states.
- Usage and financial-control records: quota consumption, credit movements, estimated/settled provider costs, reservation status and billing references. Do not store payment-card credentials unless a separately reviewed payment integration requires it.
- Security and diagnostic data: IP/network metadata, request timestamps, device/browser information and security events, only to the extent actually collected by deployed services.
- Support correspondence: information users choose to send to the operator.

**Before publication:** verify all categories against frontend analytics, CDN/hosting logs, Render, Supabase, GitHub Pages, error monitoring, authentication, payment and AI-provider configurations. Remove categories not collected; add any category that is.

## 3. Why data is processed

Subject to the lawful basis confirmed by counsel, data may be processed to create and secure accounts; provide requested AI-assisted creative features; manage generation jobs and deliver results; enforce quotas and prevent abuse; reconcile AI-provider usage and costs; troubleshoot, maintain and secure the service; respond to support requests; and comply with legal obligations.

Do not reuse private prompts, uploads or outputs for advertising, public galleries, model training or unrelated analytics unless a separate valid legal basis and clear opt-in are implemented.

## 4. DeepSeek and other external recipients

When a user submits a request to a DeepSeek-powered feature, PWA Studio sends the minimum required request content to DeepSeek's API through the server. The browser must never receive the provider API key.

For Vision analysis, the intended payload includes the user's prompt and one validated, normalized image. The image is processed in memory by PWA Studio, stripped of EXIF/GPS and other ancillary metadata where supported, and sent only after an explicit, feature-specific confirmation. PWA Studio's current implementation does not intentionally persist the source image in its own database or object storage. This does not mean the provider cannot retain or process the payload under its own API terms.

Before launch, identify the exact DeepSeek API legal entity, API product terms, data-processing terms (if any), subprocessors, processing/storage locations, retention periods, deletion process, model-training/optimization practices, security commitments, and any available opt-out. Do not infer these terms from DeepSeek's consumer-app privacy policy. The public DeepSeek Privacy Policy states that downstream applications using open-platform services are outside that policy's scope and that the developer must disclose its own processing policy. Its consumer-service policy describes processing/storage in China; the API-specific position must be verified directly and contractually.

Other recipients may include [LIST ONLY CONFIRMED AUTHENTICATION, HOSTING, STORAGE, EMAIL, PAYMENT, ANALYTICS AND SUPPORT PROVIDERS], each with its role, purpose, country, applicable terms and retention.

## 5. International transfers and data location

PWA Studio must disclose each country to which personal data is transferred or made accessible, including actual hosting, database, backup, support and AI-provider locations. [INSERT VERIFIED DATA-FLOW TABLE AND COUNTRIES.]

For users in Kazakhstan, counsel must assess the Personal Data and Their Protection Law, including local database/storage requirements, consent requirements, cross-border transfers, security measures and sector-specific restrictions. A user's checkbox is not a substitute for confirming that the transfer is legally permitted and that local storage and security obligations are met. Do not enable DeepSeek Vision for Kazakhstan users until the operator has verified the API destination and obtained a documented legal assessment.

## 6. Retention and deletion

PWA Studio must publish a precise retention schedule before launch. The operator must verify and document retention for each category:

| Data category | Actual storage system / country | Retention period | Deletion method / exceptions |
|---|---|---|---|
| Account data | [VERIFY] | [SET] | [VERIFY] |
| Prompts and assistant history | [VERIFY] | [SET] | [VERIFY] |
| Uploaded source media | Intended not to be persisted for Vision; verify other features | [SET] | [VERIFY] |
| Generated media and job results | [VERIFY] | [SET] | [VERIFY] |
| Financial ledger and audit records | [VERIFY] | [SET; legal/accounting basis] | [VERIFY] |
| Security and infrastructure logs | [VERIFY each provider] | [SET] | [VERIFY] |
| Backups | [VERIFY] | [SET] | [VERIFY] |
| DeepSeek API payloads | DeepSeek API; exact region and retention [VERIFY CONTRACT] | [VERIFY CONTRACT] | [VERIFY CONTRACT] |

A statement that PWA Studio does not store a Vision source image refers only to the application's intended own-storage behavior. It cannot promise deletion from DeepSeek or infrastructure logs without verified provider commitments. Deletion requests may be subject to legal retention duties; explain applicable exceptions only after counsel review.

## 7. Your choices and rights

Depending on applicable law, users may be able to request access, correction, deletion, restriction, objection, portability, or withdrawal of consent. The operator must provide a monitored contact channel and a documented identity-verification and response workflow.

**Privacy contact:** [EMAIL]  
**How to submit a request:** [PROCESS / RESPONSE TIME / IDENTITY VERIFICATION]  
**How to complain to the competent authority:** [COUNSEL TO COMPLETE]

Withdrawing consent should stop future processing that depends on that consent where technically and legally possible. It cannot reverse processing that already occurred or guarantee deletion from an independent provider unless that provider's terms and procedures allow it.

## 8. Security

PWA Studio applies technical and organizational safeguards appropriate to the service, including server-side provider credentials, authentication and authorization checks, request limits, bounded uploads, private storage for supported generated results, cost admission controls and restrictions on sensitive logging. No internet transmission or system can be guaranteed completely secure. The final public notice must describe only safeguards actually deployed and tested.

## 9. Sensitive information, other people and children

Do not submit government identifiers, financial account data, passwords, private correspondence, health records, biometric identifiers, precise location, confidential business secrets, intimate imagery, or other sensitive information unless the specific feature is approved for that data and the operator has completed a separate legal and security review.

Do not upload another person's image, voice, personal data or copyrighted material unless you have the necessary rights, permissions and lawful basis. Do not upload images of children or other vulnerable people to Vision. Age limits and parental-consent rules must be set and reviewed for each launch market before public release.

## 10. AI outputs

AI outputs may be inaccurate, incomplete, non-unique or unsuitable for a particular purpose. Review outputs before relying on or publishing them. This notice does not transfer ownership of source material or determine copyright in AI-generated outputs; those matters belong in separate rights and licensing terms.

## 11. Changes

Material changes to purposes, providers, data categories, transfer countries or retention must trigger an updated notice and, where required, renewed consent before the changed processing begins.

## Mandatory publication checklist

- [ ] Identify the legal operator and verified contact details.
- [ ] Inventory every data field, endpoint, browser storage location, log and connected service.
- [ ] Confirm Render, Supabase, CDN, backup and support regions and contractual terms.
- [ ] Obtain and review DeepSeek's actual API agreement, API privacy/data-processing terms, retention, location, subprocessors and training/optimization terms.
- [ ] Complete a Kazakhstan data-protection and cross-border-transfer assessment if serving Kazakhstan residents; assess local storage requirements independently.
- [ ] Set enforceable retention and deletion periods for every category.
- [ ] Implement privacy request, consent withdrawal, incident response and account deletion workflows.
- [ ] Confirm age policy and handling of third-party images and personal data.
- [ ] Publish the approved notice in the product before collecting data under it.
- [ ] Obtain counsel sign-off and record the approved version/date.

**Release gate:** Until all items above are complete, this document remains an internal draft and Vision must remain disabled.

## Research references for counsel (checked 23 November 2026)

These are starting points, not a complete legal analysis and not a substitute for current local-language legislation or API-specific contractual documents:

- DeepSeek Privacy Policy (last updated 10 February 2026): https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html
- DeepSeek Terms of Use (last updated 27 March 2026): https://cdn.deepseek.com/policies/en-US/deepseek-terms-of-use.html
- Kazakhstan Law on Personal Data and Their Protection, Article 16 cross-border transfers (official Adilet publication; verify current consolidated text and amendments): https://old.adilet.zan.kz/eng/docs/Z1300000094
- Kazakhstan government personal-data protection recommendations: https://www.gov.kz/uploads/2023/2/17/c06d0fc1fb31b7fe5b66a762a73417c7_original.2052451.pdf

Important distinction: DeepSeek's published consumer-service Privacy Policy says it does not cover personal-data processing for end users of downstream applications built with its open-platform services; it directs the developer operating the application to disclose its own policy. Therefore, this draft does not treat that consumer policy as proof of the API's exact retention, processing location, deletion or model-improvement terms. Obtain and review the API-specific agreement and any data-processing addendum directly.
