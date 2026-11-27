# Character Library — account isolation

## Current local-storage boundary

The Character Library remains browser-local. It is not yet a cloud-synced library.

- Passport metadata is stored under a user-specific localStorage key:
  `pwa-studio-character-library-v1:<auth user UUID>`.
- Guest metadata uses the separate `...:guest` key.
- Reference image Blobs live in IndexedDB and each row stores its `ownerId`.
- Image reads return a Blob only when the stored owner matches the current owner.
- Image deletion checks the stored owner before deleting a row.
- On account identity changes, the auth UI increments `authContextVersion`, clears account-bound panels, and dispatches `pwa-studio-auth-changed`. The Character Library resets its editor and rerenders.

## Async account-switch fencing

Rendering, saving, and deleting capture the starting owner and auth-context version.

- A render stops if the identity changes while an image read is pending.
- A save captures the starting storage key and checks the identity before and after asynchronous image writes. A stale save cannot write its passport into the next account's localStorage.
- A delete captures the starting storage key and owner, checks the context after confirmation, and does not report completion into a different account's UI.
- Newly written image Blobs from an interrupted save may remain as unreferenced rows under the original owner. They are not reassigned to another owner and are deliberately not auto-deleted by this guard.

## Security scope and limitations

This is an application-level separation of browser-local data, not a cryptographic security boundary. Anyone with access to the same browser profile or developer tools may inspect local browser storage. It does not replace server-side ownership checks, Supabase RLS, or authenticated API authorization.

Cloud backup remains disabled in the UI until the server-side upload/read-back coordinator and its acceptance tests are complete. No production migration or deployment is implied by this document.
