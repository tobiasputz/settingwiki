# Seeker 10.3.0 — Living World integration release

This is an additive upgrade to the user's Seeker 10.2.0 source, **not** a clean-room replacement.
The original application, Foundry bridge, templates, Atlas assets and existing APIs are retained.

## Implemented in application code

- **Campaign consequence ledger**: SQLite-backed GM private drafts, explicitly published player-safe title/summary, campaign/session/object/map/marker links, edit and archive, cross-campaign validation and a separate allowlisted player API. New files: `app/world_state.py`, `app/route_world_state.py`.
- **Campaign Workspace**: World editor, player-visible update feed, four-step navigation shortcuts, cross-links from the GM object inspector and Atlas, and a session closeout consequence draft. New files: `static/world-state.js`, `static/world-state.css`.
- **Atlas**: Auto/High/Eco detail selector with persistent local preference, low-detail albedo in world view and full-resolution GPU albedo selection when zoomed, reduced shading work in Eco mode, recoverable 2D display on lost WebGL context, GM event history in the marker drawer. Existing 2.5D shader and UV projection retained.
- **Codex**: Focus reading mode, scalable body text and optional local reading-position restoration; server-side knowledge rules unchanged. New `static/codex-reading.js`.
- **Source safety**: Source Studio now sends the original SHA-256 source hash and the API rejects stale edits with HTTP 409. Existing edit clients without a hash remain compatible. Source snapshots and restore remain intact.
- **Foundry display**: Workspace distinguishes current heartbeats from stale/cached bridge data, without altering the protocol.
- **Testing**: New regression tests for GM-only/event visibility, explicit publication, campaign separation, stale-source conflicts and front-end wiring.

## Existing systems preserved

- LaTeX files remain authoritative for Codex content; the addition does not modify uploaded campaign source by itself.
- Foundry remains authoritative for actor state; no changes to the Bridge protocol or manifest are needed.
- Existing map markers, 2D fallback, fog of war, routes and campaign invitations remain in place.
- Existing source-backed Homebrew, Chronicle, Foundry sync, content permissions, player dossiers, and saves are retained.
- Database migration creates only an additive table and indexes. **No `.data`, SQLite files or credentials are bundled.**

## Important limits — not claimed as finished

- The Atlas still uses Seeker's existing WebGL displacement renderer; full tiled 8K GPU textures, true shadow mapping, detailed geographic relighting and League of Legends-equivalent art direction were *not* built in this release.
- The Living World ledger links events but does not infer consequences automatically from free-text transcripts or modify canonical lore without review.
- Foundry reliability improvements here are clearer stale-state reporting, not a complete rewrite of the bridge.
- The wider existing UI and theme were preserved; comprehensive redesign of every specialist screen and systematic high-fidelity visual QA remain future work.
- Full headless browser interaction tests require an unblocked Playwright Chromium instance on CI/deployment; the supplied environment blocked test web navigation.

## Upgrade process

1. **Back up** the Railway persistent project volume and database using Seeker's backup controls. Check the backup file before deploying.
2. Replace *application files* from the ZIP and deploy normally. Preserve `.data`, Railway volume mounts and environment secrets.
3. On server startup Seeker creates the additive world consequence table automatically. It keeps existing data.
4. Open Campaign Workspace > World, record an event, verify unpublished drafts are GM-only, and explicitly publish a short player-safe item.
5. Visit a Codex page to try reading preferences, and open Kiragon's Atlas for Auto/High/Eco relief modes.
6. Check Foundry connectivity and the Diagnostics page; verify existing source compilation, fog and player permissions in your own campaign.

## Reverting

Reinstall the former 10.2.0 application files (from a backup of the release) and retain the database. The new ledger table is additive and can remain unused; do not delete it without a separate data export. Restore the full prior database/volume only when specifically needed for an incident.
