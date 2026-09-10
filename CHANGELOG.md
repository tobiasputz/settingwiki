# Seeker 5.1.0 — GM runbook & stability pass

- Rebuilt **Session Prep** into a real GM runbook. Planned sessions now support structured scene cards, a movable clue/secrets pool, compact NPC quick cards, a live event log, consequence triggers, campaign clocks, a pacing strip, reusable prep templates, custom/random tables, Improv Mode, one-click player pushes, guided closeout, and automatic next-session seeding from unresolved material.
- Added a GM-only **Continuity Check** that surfaces dangling clues, pending consequences, active objectives and clocks that may deserve attention during prep.
- Added a strictly **GM-only spotlight reminder**. It is available only through authenticated GM prep/workspace routes, never appears in player templates, and never emits player notifications.
- Fixed **Session Prep scrolling** across desktop, tablet and mobile by removing the competing fixed-height scroll containers and allowing the document to own vertical scrolling; sticky session navigation remains available on larger screens.
- Repaired the **V5 narrative character dossier** layout after the V5 simplification. Portraits, story copy, overview, biography, campaign context, arcs, relationships, milestones and visual references now use a bounded responsive layout instead of the broken oversized composition seen on wide displays.
- Fixed **Atlas marker interaction**. Region/fog layers no longer intercept marker hit targets, markers are explicitly above map overlays, and marker activation is handled by a resilient delegated click path that works after re-rendering and on touch devices.
- Fixed **notification persistence** for the GM. The owner now has a stable internal reader identity, so Mark read / Mark all read survive navigation and reloads just like player read state.
- Added **notification deletion**. Players can dismiss a notification only for themselves, while the GM can permanently remove the campaign notification for everyone.
- Added optional player-visible **campaign clocks** while keeping GM-only clocks private.
- Kept all V5 campaign/session/privacy boundaries intact and added dedicated regression coverage for the new GM systems and the reported UI regressions.
- Bumped static/PWA assets to **v5100**.

# Seeker 5.0.0 — session companion

- Reframed Seeker around a simple division of labor: **Seeker remembers the campaign; Foundry and Pathbuilder remain the rules engine.** Player character pages now emphasize identity, story, goals, portraits, relationships, arcs, milestones and external Foundry/Pathbuilder links instead of duplicating a full PF2e build sheet. Legacy sheet data remains preserved in the database for backwards compatibility.
- Rebuilt **Session Mode** as the primary at-the-table player workspace. It combines current character identity, live/planned session context, collaborative party notes, private character notes, objectives, mysteries, handouts, followed lore, discoveries, recap context and map shortcuts in one responsive interface. Desktop gets a three-column command center, tablets/iPads get a deliberate two-column layout, and phones get a one-pane tabbed layout with touch-first controls and a sticky note composer.
- Added **GM Session Prep**, a campaign-aware runbook for preparing planned sessions before play. GMs can write an opening, scene/beat checklist, secrets and revelations, contingencies, scratch notes and pinned references to lore, objectives, character arcs, mysteries, fronts, handouts and maps. The same runbook is visible from the live GM session console, and a prepared session can be taken live directly from the prep workspace.
- Added a **collaborative party notebook** per session. Notes are attributed, update during play, remain attached to the session archive and can be removed by their author/GM. Private player and character-scoped journals remain separate.
- Added a private, campaign-specific **Investigation Board** where players can pin Codex entries or freeform theories, drag them around, connect them with labeled edges and remove their own nodes/links without changing GM-authored canon.
- Added player-facing **Objectives** with active/on-hold/completed/failed state, plus links into session play and prep. Objectives can be used as party-authored goals while remaining campaign-scoped.
- Added **Follow / Watch** controls for visible lore. Players can follow Codex entries and receive restrained notifications when followed lore is revealed, updated through session material or gains relevant relationships. Notification preferences, mark-all-read and category muting are included.
- Added a structured **Previously on…** briefing assembled from stored campaign data: last session recap, objectives, recent discoveries, unresolved mysteries, recent journals and lore connected to the previous session. This works without generative AI and never invents campaign facts.
- Extended the **Atlas** with campaign-specific knowledge states (Unknown, Rumored, Discovered, Visited) and optional per-campaign fog reveals. Visited locations can remember the session in which they were first reached, while shared map geometry remains canonical across tables.
- Added **session RSVP** for planned sessions (Going / Maybe / Can’t make it) and GM attendance summaries. The existing player-global availability planner remains the scheduling source of truth; RSVP is the lightweight confirmation step after a date has been chosen.
- Added **character progression milestones** for narrative snapshots and memorable changes without recreating the mechanical character sheet.
- Added real **permanent campaign deletion**. Non-default campaigns can now be deleted from campaign management; Seeker removes campaign-scoped state while preserving global player identities, global availability and shared setting canon. The default campaign remains protected from accidental deletion.
- Kept V4’s character-scoped note identity gate (“Who are you playing tonight?”), campaign privacy boundaries, semantic search, mobile schedule protections and resource-efficient caching.
- Bumped application/PWA assets to **v5000** and added V5 regression coverage for session mode, prep, party notes, investigation privacy, follows, RSVP, Atlas discovery/fog, campaign deletion, migration and responsive frontend contracts.

# Seeker 4.4.0 — player feedback & semantic search

- Reworked **Relationships** in Worldcraft into a searchable, filterable, paginated directory instead of one unbounded scroll. Relationship creation now uses delegated click handling and searchable source/target pickers, fixing Add Relationship buttons that could stop responding after a partial UI re-render.
- Hardened the **mobile Session Planner** against accidental availability changes while scrolling. Touch input now waits for a deliberate tap, cancels on finger travel/page movement, and never drag-paints on coarse touch devices; desktop mouse painting remains fast.
- Fixed the cross-campaign availability workflow with regression coverage for the exact reported sequence: fill availability in Campaign 1, create/assign a second character to Campaign 2 later, and retain the same player-level availability in both campaign planners. Availability is stored once per invitation/date and campaign rosters are derived from current characters, so one person never has duplicate calendars.
- Added **local semantic Codex search** with no API key, hosted model, or external service. Seeker combines BM25, concept expansion and setting-specific co-occurrence learned from the player-visible Codex. The index is spoiler-safe because it is built from each request's already-filtered Codex view, and its in-memory cache is deliberately bounded for Railway.
- Upgraded **Ask Seeker** to use the same local semantic retrieval by default. Optional OpenAI-compatible generation can still be enabled through environment variables, but the useful finding/retrieval layer now works entirely free.
- Added deletion controls for **Codex comments/annotations**: authors can remove their own comments and the GM can moderate any comment, while other players receive a permission error.
- Added proper **character deletion** plus GM editing/deletion of player characters. Fixed a GM-update ownership bug so editing an existing player character preserves its invitation owner instead of demanding a new owner.
- Expanded character sheets into a much more capable, player-owned builder: appearance, personality, bonds, focus, initiative, spell statistics, armor/shield, attacks/actions, resources, proficiencies, currency/bulk, inventory, spells, feats, custom sections, conditions, defenses, arcs and lore relationships. Added personal sigils, subtitles, secondary accents, density controls and additional visual themes.
- Added an **All Tables** destination and made campaign context more visually prominent on campaign-sensitive screens. Players/GM can intentionally step out to a setting-wide table overview without pretending one campaign is active.
- Expanded the **Atlas marker library** from the small original set to roughly seventy useful map symbols covering settlements, fortifications, travel, terrain, commerce, institutions, hazards, monsters, secrets and more. The atmosphere renderer now scales effect presence/intensity for high-resolution source maps, so clouds, fog, weather and magical effects remain visible on 4K maps; the intensity control now reaches 1.6.
- Bounded relationship lists on player dossier/network views and added show-more behavior to keep large settings navigable.
- Bumped application/PWA assets to **v4400** and added focused regression coverage for global scheduling, comment permissions, GM character editing/deletion, advanced-sheet round trips, semantic concept matching, touch-safety hooks, relationship controls, Atlas assets and All Tables navigation.

# Seeker 4.3.0 — session planner

- Added a **player-global availability calendar**. Each invited player fills availability once using three explicit states: Available, If necessary, and Unavailable. Blank dates remain unknown rather than being optimistically treated as free.
- Added a fast paint-style calendar UI with click/drag entry, month navigation, automatic saving, and quick-fill actions for weekends, weekdays, the whole month, or clearing a month.
- Connected scheduling to **character campaign assignment** instead of duplicating calendars per table. A player with characters in two campaigns automatically contributes the same availability to both campaign planners, and a player with two characters in one campaign is counted only once.
- Players may now choose any active campaign directly in the character editor. Assigning their own character to a new active campaign automatically grants that invitation table access; GMs can still explicitly revoke campaign membership.
- Added a GM Session Planner that shows the earliest date where every current player is available, the earliest fully-answered date that works only “if necessary,” candidate dates, per-day attendance breakdowns, and the campaign scheduling roster.
- The scheduling roster is derived from non-retired player characters plus current campaign access. Retired, dead, and inactive characters do not keep a player in scheduling calculations, and manually revoked campaign access is respected.
- Availability rows are indexed and saved in batches; the planner does no background polling, so adding scheduling does not create recurring Railway load.
- Added Session Planner entry points to player navigation, mobile More, Session quick actions, GM tools, and Worldcraft campaign cards.
- Bumped application/PWA assets to **v4300** and added regression coverage for global cross-campaign availability, green/soft/blocked/unknown date classification, duplicate-character deduplication, character-driven campaign joining, and player/GM HTTP flows.

# Seeker 4.2.0 — multi-campaign setting support

- Added first-class **Campaigns** so one Seeker setting can host several simultaneous tables without duplicating the Codex or Atlas.
- Existing single-campaign installations migrate automatically into a preserved **Main Campaign**; existing invitations, characters, sessions, journals, reveals and knowledge remain attached to it.
- Added campaign membership: one player invitation may participate in one or several campaigns. The owner assigns players per campaign from **Worldcraft → Campaigns**.
- Scoped player characters, live/session history, session updates, character/player journals, mysteries, handouts, fronts, rumors, plot threads, submissions, notifications, per-player knowledge and progressive lore reveals by campaign.
- Kept canonical setting material shared: LaTeX/Codex lore, Atlas maps, historical chronology, semantic relationships and other setting-level authoring remain one source of truth.
- Added a compact table switcher for players and GMs. Character identity is cleared when switching campaigns so a PC from one table can never leak into another table's session notes.
- Added a campaign manager with description/accent, active/archive state, default campaign, member assignment, and quick table switching. Archived campaigns remain preserved but disappear from player switching.
- Campaign access fails closed: if an invitation is removed from every active campaign, it cannot fall through into the default table or see another party's state.
- Made Codex spoiler filtering, article provenance, live-session heartbeat, notifications and character search campaign-aware while retaining the v4.1 caching/resource optimizations.
- Bumped PWA/static assets to **v4200** and added regression coverage for migration, campaign isolation, membership enforcement and player switching.

# Seeker 4.1.1 — Codex navigation hotfix

- Fixed a SQLite compound-query regression in article provenance lookup that caused `/wiki/<slug>` pages to return HTTP 500 after the v4.1 backend optimization.
- Kept the optimized single-query provenance lookup, but now applies the `COALESCE(session_number, ...)` ordering outside the UNION where SQLite permits expression ordering.
- Added a regression test covering lore references, session updates, deduplication, and unnumbered-session sorting.

# Seeker 4.1.0 — final identity & release hardening

- Renamed the product identity to **Seeker** across the player UI, GM tools, PWA metadata, documentation, local launch scripts and user-facing download names. Legacy `loreforge-*` LaTeX directives, browser-storage keys, database/archive identifiers and environment-variable fallbacks remain supported deliberately so an upgrade does not lose campaigns, notes, offline state or saved preferences.
- Reworded the most generic player-facing surfaces into a clearer Seeker voice: the home page is now **Seeker’s Archive**, the Codex presents the **known world**, historical navigation uses **Chronicle of Ages**, player-maintained objectives are **Threads worth following**, and GM navigation uses more campaign-shaped language without obscuring what controls do.
- Added a bounded **per-access Codex view cache** on top of the parsed wiki cache. Repeat article navigation now performs only a small SQLite revision-fingerprint query when nothing relevant changed instead of reconstructing reveal, publication, style, relationship, alias, variant and per-player knowledge state for every click. Ordinary activity logging no longer invalidates that cache.
- Removed several remaining N+1 query patterns in fronts, thread notes/links, mysteries, character images and historical map-region data, and added matching hot-path indexes for persistent Railway databases.
- Changed player contribution, GM inbox, character-art and map uploads to **1 MB streamed chunks with hard size limits**, preventing 15–100 MB request bodies from being duplicated into Python memory.
- Hardened heavy build work: XeLaTeX/latexmk output is spooled to a temporary file with only a bounded diagnostic tail retained in memory, automatic PDF compilation on process startup is disabled unless explicitly enabled, and compile/rebuild/import operations share a non-blocking build lock so concurrent GM actions cannot launch overlapping TeX jobs.
- Added runtime diagnostics in Studio for current/peak web-process RSS, peak child-process RSS, build state and log cap. This makes future Railway memory spikes attributable instead of opaque.
- Reduced live-session background load with visibility-aware polling and a lightweight session-pulse endpoint; stale searches are aborted and hover-preview caches are bounded.
- Kept v4’s character-scoped sessions/journals, first-run Quick Tour, mobile player UI and all upgrade migrations intact.
- Bumped application/PWA assets to **v4100** and retained network-first static caching so deployed fixes replace stale browser bundles promptly.

# Seeker 4.0.0 — player-first sessions & quality of life

- Added **session character identity**. Players with multiple PCs can enter each live session as a specific character, switch deliberately, or remain player-wide. The selected identity is remembered for that live session only, so the next session can prompt again when appropriate.
- Made **player journals character-scoped**. A note attached to one character is hidden when that same player enters as another character; player-wide notes remain available separately. Existing v3 journals migrate safely as player-wide notes. Party-shared notes from other players remain visible according to their normal visibility rules.
- Added character ownership validation to journal writes so a player cannot attach a private note to somebody else's character by crafting an API request.
- Improved journal usability with **draft autosave/recovery**, character filters, readable session labels, and a session picker that uses session number/title instead of raw database IDs.
- Reworked the desktop header into a calmer player-first navigation: core destinations remain one click away, secondary lore tools live under **Explore**, and GM-only destinations live under one **GM** menu instead of filling the top bar. Mobile navigation keeps its dedicated touch layout.
- Added a **role-aware Quick Tour** for players and GMs. It launches on first use, adapts to the current screen/role, supports keyboard navigation, and can be replayed any time from Explore, mobile More, or GM toolbars.
- Improved the global search palette with **quick jumps** and a **recently viewed lore** section before the player starts typing, reducing navigation friction at the table.
- Bumped all application/PWA asset caches to v4000 so existing installations fetch the v4 JavaScript/CSS instead of retaining older cached UI code.
- Added regression coverage for character-scoped journal isolation, cross-player ownership checks, v3 journal migration, session identity switching, v4 assets, and cache-version consistency.

# Seeker 3.0.2 — Studio stale-cache recovery

- Fixed the upgrade path that could keep serving the broken v3.0.0 Campaign Studio JavaScript even after the v3.0.1 source fix was deployed. The PWA service worker had cached all `/static/*` assets cache-first while the HTML continued to request `admin.js?v=3000`, so an existing browser could remain pinned to the old file indefinitely.
- Bumped application asset URLs and PWA cache namespaces to v3002 so existing installations request a fresh Studio bundle immediately.
- Changed service-worker handling for static assets to **network-first with cached fallback**: online clients receive the deployed JavaScript instead of a stale cached copy, while previously cached assets still work offline.
- Added no-cache headers to `/sw.js` so browsers can discover service-worker updates promptly.
- Marked the Campaign Studio HTML response `no-store` so a browser cannot retain an older page that still references the obsolete asset URL.
- Added regression coverage for Studio helper presence, asset-version consistency, stale-cache prevention, and service-worker update headers.

# Seeker 3.0.1 — Campaign Studio startup regression fix

- Restored the Campaign Studio `refreshStatus()`, `refreshFiles()`, and `renderFileTree()` helpers that were accidentally dropped during the tabbed-editor refactor. Their absence threw during Studio startup and prevented later initialization, including Access controls.
- Reconnected project status, PDF readiness, project-health messaging, file filtering/selection, and the main-file selector to the restored refresh flow.
- Added regression coverage so the Studio bootstrap helpers cannot silently disappear again.

# Seeker 3.0.0 — Living world, player agency & campaign memory

- Added a formal **Lore vs. State** architecture. Canonical setting prose remains in LaTeX; mutable campaign state (where people are, what factions are doing, what players know, and what is currently unresolved) lives in Seeker metadata instead of polluting the manuscript.
- Added **per-player knowledge state** for lore/state targets so different invited players can know, suspect, or remain unaware of different facts without duplicating Codex pages.
- Added **Campaign Fronts** with clocks, status, goals, stakes and advancement history for factions, threats, wars and off-screen projects.
- Added **runtime NPC/entity state** for current location, status, attitude, faction, objective, last appearance and other volatile campaign facts.
- Added **relationship history**, plus specialized family-tree / organization-chart relationships, so connections can change over historical time instead of being one permanent edge.
- Added **historical map regions** with polygon borders and dated variants. Region shapes can change across eras and the Atlas API can resolve the appropriate boundary at a selected historical date.
- Added the **Rumor Engine** with truth classification, location/faction targeting, heard state and GM-controlled sharing. Players only receive the rumor text, never the hidden truth classification.
- Added first-class **Threads** for quests, mysteries and plotlines. Threads may be player-owned, party-editable or GM-owned; players can maintain status, notes, clues, theories, unresolved questions and lore links themselves while the GM retains correction/supplement powers.
- Added **note authorship protection** inside shared threads: another player cannot overwrite somebody else's note, while the GM may annotate/correct it with an explicit GM-edited marker.
- Added **player journals** (private or party-visible), character arcs, promises/goals, and character relationship notes. These live with the invited player's identity rather than in canonical LaTeX.
- Added **player submissions** for proposed lore, recaps, relationship ideas and worldbuilding, with GM approval/rejection instead of direct canonical-source editing. Submissions and GM Inbox items support file/image uploads.
- Added a fast **GM Inbox** for notes, NPC/location ideas, reminders, photos and browser-recorded voice memos to classify after the session.
- Added **staged publishing** (Draft / Ready / Published) so the GM can prepare several related Codex changes and release them together after a session.
- Added **session state snapshots** and provenance so Seeker can answer what changed around a session and where an entry appeared/revealed over campaign history.
- Added a **notification/live-push layer** for discoveries and session spotlights. Player Session surfaces newly delivered information without requiring players to manually hunt through the Codex.
- Added **continuity checks and lore suggestions** for runtime/lore conflicts, missing relationships and opportunities to connect prose to existing lore. Suggestions are approval-only and never rewrite source automatically.
- Added a dedicated **Media Library** with asset kinds/tags, focal points, alt text, usage lookup, thumbnails and owner-only reference replacement across LaTeX + supported metadata.
- Added **Foundry-compatible journal/character export** endpoints rather than duplicating combat automation already handled by PF2e VTT tooling.
- Added **portable campaign archives** containing source, uploads, database and a manifest, plus a non-destructive restore-integrity test before trusting a backup.
- Added **read-only archive mode** for freezing a completed campaign while retaining its Codex, characters and campaign history.
- Added role-aware collaboration: **Owner, Co-GM, Player, Observer and Guest**. Co-GMs can run campaign-state/world tools without receiving owner-only infrastructure/export powers; observers/guests are read-only.
- Added a spoiler-aware **campaign assistant endpoint** that uses only the lore/state visible to the requesting role/player. It is infrastructure-ready and remains opt-in rather than forcing an AI provider on the deployment.
- Rebuilt **Campaign Control → Living Campaign** around task-oriented panels for Fronts, State, Knowledge, Threads, Rumors, Relationship History, Hierarchies, Historical Regions, Publishing, Submissions, Inbox, Roles, Media, Continuity and Archive/Export.
- Expanded Player Session and Campaign pages so party-maintained threads, journals and character-owned state are reachable from phone/tablet play rather than living only in GM screens.
- Added regression coverage for player/party authorship boundaries, observer/co-GM permissions, archive freeze behavior, historical polygon round-trips, media usage/replacement, portable archive integrity, mobile player-session integration, and owner-only backup testing.

# Seeker 2.1.0 — World Builder, readable network & player characters

- Rebuilt the **Lore Network** around readable story relationships instead of drawing every heading at once. Story mode caps noisy automatic references, prioritizes Person-of-Note/entity links and explicit semantic relationships, hides unconnected nodes, suppresses label clutter, supports chapter/search filters, and adds correct responsive pan/zoom plus two-finger pinch on touch devices. The false “No links yet” overlay is fixed.
- Turned **Timeline** into a dedicated **Historical Chronicle**. GMs can create eras, date ranges, wars, reigns, discoveries, treaties, catastrophes, revolutions and other turning points; events have significance and historical certainty, while session recaps/festivals no longer clutter the historical view.
- Rebuilt **Campaign Control → World Builder** as a visual authoring workflow: structured month/week/moon editors, geography/travel controls, world-health progress, purpose-based lore templates, and direct jumps into History, Relationships and Atlas tools.
- Added **Create entry in Campaign Studio** from World Builder. It creates a normal LaTeX file under `Worldbuilding/`, revision-safely wires it into the main document, and opens that file directly in the Studio editor. A non-mutating “Copy LaTeX scaffold” option remains available.
- Added **Obsidian-style source tabs** to Campaign Studio. Multiple `.tex`/source files can stay open, dirty state is shown per tab, files can be closed individually, and internal Seeker navigation now stays in the same app window rather than spawning browser windows.
- Added a persistent GM mode switcher between **Player / Session / Studio / Control** and expanded tablet behavior. iPad-sized screens now use the same Files / Editor / Preview single-pane authoring model as phones instead of squeezing the desktop three-pane layout into a narrow viewport.
- Added a first-class **Player Characters** shelf. Each invited player can own multiple characters, edit biography/goals/status/profile information, choose party-visible or private-to-player+GM visibility, upload portraits, gallery art and inspiration references, and manage retired/alternate characters. GMs can inspect/edit every character.
- Player characters are available from desktop navigation, the mobile bottom bar, Player Session quick actions, Campaign Control → Party, and global search. Private character dossiers and their uploaded images remain inaccessible to other players even if an asset URL is guessed.
- Updated PWA/offline routing so character dossiers and their media are treated as invitation-protected campaign content.
- Added regression coverage for historical eras, timeline filtering, multiple/private player characters, private character assets/search, direct World Builder file creation, network/mobile UI shipping, and existing v2 functionality.

# Seeker 2.0.0 — living campaign platform

- Added dedicated **GM Session Mode** and **Player Session Mode** with live session state, spotlight lore/maps, discoveries, handouts, recaps, current location, and session history.
- Added **progressive lore** (hidden / rumor / discovered / public), party or player-specific audiences, temporary reveals, unreliable-knowledge variants, and an editor **Reveal** composer that wraps selected LaTeX prose without changing the canonical PDF.
- Added campaign **Timeline** and configurable fantasy **World Calendar**, including festivals, moons, seasons, current campaign date, and lore-linked historical events.
- Added semantic relationships, aliases/redirects, dossiers, heraldry/accent identities, galleries, backlinks, hover previews, and the interactive Lore Network.
- Added player private/party annotations, GM-only notes, bookmarks, recent-reading trails, and a “what changed” discovery feed.
- Added **Mystery Boards** with clue cards and editable red-string connections; player boards render those connections while GM-only clues/strings never leak through public endpoints.
- Added immersive **Handouts** (letters, parchment, newspapers, wanted posters, journals/visions) plus session-linked delivery.
- Expanded the Atlas with layers, discovery fog, travel estimates, and existing edge-locked animated fantasy atmosphere controls.
- Added campaign health checks, source snapshots/restore, dynamic LaTeX entry templates, richer campaign-control dashboards, and session-centric GM workflows.
- Added an installable **PWA** and purpose-built phone/iPad layouts: iOS/iPadOS supports Safari → Share → Add to Home Screen; Android/Chrome supports Install app. Player navigation becomes a touch-friendly bottom tab bar and admin/editor panes become switchable touch views. Offline campaign caching is explicit opt-in and isolated per invitation identity.
- Kept **personal invitation links** as the default player access model, with revocation/rotation/device limits enforced across Codex, maps, search, media, sessions, and PWA-private content.
- Made the GM editor toolbar/top bar persistent while editing long files; mobile/tablet editor controls remain sticky.
- Added regression coverage for v2 privacy boundaries, session routes, PWA/mobile shell, mystery connections, progressive-lore rendering, maps, snapshots, and existing invitation/build behavior.

## 1.4.0 — personal invitation access + GM source bridge

- Replaced the shared player-password assumption with **invitation-only access by default**. Every player can receive a unique signed bearer link from **Admin → Access**; there is no shared secret to distribute.
- Added an Access workspace for creating, copying, expiring, revoking, restoring, rotating, and deleting personal invitations. Usage count, last-used time, and remembered browser/device count are shown per invitation.
- Invitations can optionally be limited to a set number of browsers/devices. Reopening the link in the same remembered browser reuses its slot; the GM can reset remembered devices without changing the invitation URL.
- Opening an invitation while already logged in as GM does not consume a player device slot, so testing/copying links cannot accidentally lock a one-device invitation.
- Invitation links are signed with the persistent Seeker session secret. The database stores an invitation nonce/version rather than a reusable global player password; rotating a link increments its access version and immediately invalidates old links and existing player sessions.
- Revocation is checked on every protected request, including Codex pages, Atlas pages/assets, Lore Network, search, project images, uploaded map art, and PDF preview. Static application assets and the health endpoint remain public.
- Added three player access modes: **Invitation links only** (default/recommended), legacy shared `PLAYER_PASSWORD`, and fully public. Creating an invitation automatically moves the site back to invite-only mode.
- Railway deployments now default session cookies to Secure; local HTTP development remains supported.
- Added a persistent **Edit source** control when the GM reads the player-facing Codex while logged in as admin. It opens the correct LaTeX file directly in Campaign Studio at the entry's source line.
- Long Person-of-Note/entity articles now retain source locations for nested sections. As the GM scrolls through Biography/Profile/etc., the floating edit control follows the active section and opens that exact LaTeX line.
- Admin deep links support `?file=...&line=...&from=...`, focus the CodeMirror cursor on the requested source line, and show **Back to entry** for a fast read → edit → return workflow.
- Added regression coverage for invitation signing, expiry, rotation/revocation, per-device limits/reset, live-session invalidation, admin bypass, and nested-heading source-line retention.

## 1.3.11 — section-card navigation art

- Restored the earlier Codex visual hierarchy: automatic first-image artwork now belongs to the **whole large chapter/section block**, not behind each individual entry headline.
- The reading sidebar and entry links are text-only again; the small thumbnail treatment remains disabled.
- Automatic section art is still enabled by default. Seeker uses the first meaningful image found in that chapter, while skipping PF2e action-symbol utility images.
- Explicit chapter artwork overrides the automatic section image. Entry-level TOC artwork remains deliberate metadata and is no longer auto-painted behind every navigation row.
- Updated Project settings and Codex Studio copy/preview so the behavior is clear: `AUTO · SECTION BACKGROUND` is shown for automatically illustrated chapter cards.
- Added regression coverage for section-level image promotion and for keeping individual entry navigation free of automatic image backgrounds.

# Changelog

## 1.3.10 — zero-copy PDF previews and ENOSPC false-failure fix

- Fixed the remaining false `Compilation failed` state for very large successful PDFs. The TeX pipeline could finish cleanly, then Seeker would duplicate `project/main.pdf` into `build/campaign.pdf`; if that second ~100+ MB copy filled the Railway volume, the filesystem error was swallowed and the successful TeX tail was displayed as the supposed blocker.
- Seeker no longer duplicates compiled PDF bytes. `/preview/pdf` serves the canonical project PDF directly and `build/campaign.pdf` is now only an optional zero-copy symlink/hardlink alias.
- Before a new compile, an obsolete full-copy `build/campaign.pdf` from older versions is removed when the canonical project PDF still exists, immediately reclaiming the duplicate storage before XeLaTeX needs room for a new output.
- Failure to create the optional preview alias can no longer turn a successful TeX build into a failed build; the preview falls back to the canonical PDF.
- Persisting the optional build log is now best-effort, so a nearly full volume cannot retroactively invalidate a finished PDF.
- Storage reporting no longer follows symlinked PDF previews and therefore does not misleadingly count the same file twice.
- Added regression coverage for zero-copy large-PDF publishing, legacy preview reclamation, and ENOSPC-like alias failures.

## 1.3.9 — terminal-pass success detection

- Fixed the remaining false-negative XeLaTeX build state where an earlier failed latexmk pass in the same combined log poisoned a later successful `xdvipdfmx`/PDF pass.
- Final PDF reconciliation is now chronological: a strong success witness (`N bytes written`, `Output written on main.pdf`, or `All targets (main.pdf) are up-to-date`) is accepted when it occurs after the last fatal marker.
- Successful terminal PDF evidence is checked before Seeker launches stale-state retries, preventing unnecessary recompilation of very large campaign books.
- A fatal/error marker that occurs after the final PDF success witness still correctly keeps the build failed.
- Added regression coverage matching the reported 347-page Railway log: early `gave an error`/collected summary followed by `144035686 bytes written` and a final up-to-date `main.pdf`.

## 1.3.8 — Successful-PDF reconciliation

- Fixed a false compile failure where XeLaTeX/xdvipdfmx successfully wrote `main.pdf` but `latexmk` retained a non-zero wrapper status.
- Seeker now verifies the final PDF and accepts strong success witnesses such as `All targets (main.pdf) are up-to-date` or a fresh `N bytes written` converter result when no real TeX errors are present.
- Prevents the successful end of a 300+ page build from being displayed as `FIRST BLOCKING ERROR`.
- Avoids launching an unnecessary direct XeLaTeX diagnostic pass after a final PDF has already been proven good.

# v1.3.6 — large-book XeLaTeX pipeline recovery

- Fixed a major large-project bug where `LATEX_ENGINE=auto` resolving to XeLaTeX was treated as a fresh engine switch on **every compile**. Seeker now remembers the effective engine, so `.aux`, `.toc`, `.fdb_latexmk`, and related incremental state are only cleared when the engine actually changes (or when the GM explicitly requests a clean build).
- Added adaptive build windows for large XeLaTeX/LuaLaTeX campaign books. Projects with many source files or image assets receive a longer per-stage allowance while `LATEX_TIMEOUT` remains the minimum configured timeout.
- Added first-class XeLaTeX **XDV → PDF recovery**. When XeLaTeX has successfully produced a fresh `.xdv` but the outer `latexmk` stage fails or times out before PDF conversion, Seeker invokes `xdvipdfmx` separately and can recover the build without re-typesetting hundreds of pages.
- If `xdvipdfmx` itself fails, Build Doctor now surfaces the converter's actual fatal message instead of showing the harmless end of the XeLaTeX transcript (`Output written on main.xdv ...`) as the blocking error.
- FIRST BLOCKING ERROR now prioritizes the pipeline/controller log before appending the potentially huge TeX engine log, so timeout/conversion failures can no longer be pushed out of view by a 300+ page transcript.
- Added regression coverage for XDV recovery, adaptive pipeline diagnostics, and preserving incremental auxiliary state across repeated AUTO → XeLaTeX builds.

## v1.3.4 — visible blocking diagnostics

- Failed builds now always expose a **First blocking error** excerpt even when TeX does not emit a parseable `file.tex:line` diagnostic.
- Build Doctor uses a `-halt-on-error` direct-engine probe when latexmk only reports wrapper-level failure, producing a concise first-failure trace.
- Added **Copy diagnostic bundle** with the blocker, structured errors, and recent log tail for easy bug reports.
- The full raw engine log remains available below the summary.


## 1.3.3

- Added **Apply all safe fixes** to Build Doctor. All high-confidence repairs from the current compile can now be verified as one batch, revision-backed, applied without partial writes, and recompiled only once.
- Added a revision-safe **geometry consolidation** repair. Repeated dedicated `\usepackage[...]{geometry}` declarations are collapsed into one package load plus `\geometry{...}`; options are merged and later keyed values win (for example `margin=0in` followed by `margin=1in` becomes `margin=1in`).
- Build Doctor quick fixes can now contain several verified line edits, which allows project-level repairs while retaining stale-diagnostic protection.
- Added an atomic batch source-fix API: every target line is checked before any file is changed; if one line has changed since the compile, the entire batch is rejected. Each affected file is archived once in revision history before writing.
- Added regression tests for duplicate-geometry consolidation and multi-file/batch-safe repair behavior.

## 1.3.2

- Added conservative one-click **Build Doctor quick fixes** for high-confidence imported-source mistakes. The current set repairs stray `\\` after headings / `multicols` boundaries, missing `{2}` on bare `\begin{multicols}`, `\subsubection` typos, and accidental sentence-start `\The`. Every fix verifies the exact original line, uses Seeker revision history, and recompiles immediately.
- Build Doctor no longer treats every `Missing number` as a dimension problem: bare `multicols` environments are diagnosed specifically as missing the required column count.
- Seeker now keeps and previews a **fresh PDF generated despite LaTeX errors**, similar to Overleaf's recoverable-error workflow. The build remains visibly marked as having source errors so a partial PDF is never mistaken for a clean final build.
- Improved the build panel with explicit `PDF produced with source errors` state and quick-repair controls attached directly to the relevant diagnostics.

## 1.3.1

- Removed automatic first-image thumbnails from compact Codex navigation. Sidebar navigation is now clean, text-first, and never shows arbitrary action-symbol or decorative-image crops.
- Table-of-contents artwork is now deliberate: choose an image in Codex Studio, or explicitly click **Use first entry image**. Nothing is auto-promoted anymore.
- Manually selected entry TOC artwork is rendered as a subtle full-row backdrop in the main Codex instead of a tiny square icon; chapter artwork and large featured cards remain intact.
- Improved Build Doctor wording so engine/cache adjustments are not described as a successful recovery when the underlying LaTeX source still contains errors.
- Added source excerpts directly beneath clickable compile diagnostics and targeted explanations for `geometry` option clashes, stray `\\` line breaks, invalid dimensions, and mismatched environments. These diagnostics are read-only and never rewrite the campaign source.


## 1.3.0

- Fixed `fontspec` projects being sent to pdfLaTeX. Seeker now detects `fontspec`, `\setmainfont`, `\setsansfont`, `\setmonofont`, `unicode-math`, and Lua-only source across `.tex`, `.sty`, and `.cls` files and automatically selects XeLaTeX/LuaLaTeX even when an older Railway environment still says `LATEX_ENGINE=pdflatex`.
- When the effective engine changes, Seeker clears only generated dependency/auxiliary state before compiling so stale pdfLaTeX `.fdb_latexmk` data cannot poison the first XeLaTeX build.
- Added OpenType TeX Gyre and EB Garamond system fonts plus fontconfig to the Docker image. The Docker build now validates that **TeX Gyre Adventor** and **EB Garamond** are actually discoverable before the image succeeds.
- Improved Build Doctor so the `fontspec + pdfTeX` failure is identified as an engine mismatch rather than incorrectly reported as a missing font. The build panel now shows the effective engine on both successful and failed builds.
- Added first-class player-Codex rendering for the supplied PF2e campaign macros: `\feat`, `\action`, `\itemtemplate`, `monster`, `\monstersection`, `\monsterline`, `\monsterabilityscores`, `\monsterdefenses`, `\monsterspeed`, `\monsterattack`, `\monsterspellcasting`, and `\monsterability`.
- Added native inline rendering for `\actionOne`, `\actionTwo`, `\actionThree`, `\reaction`, and `\freeAction`, using the project's `Images/Symbols/` art where available and a readable fallback otherwise.
- Added native handling for the legacy `\image{width}{path}` helper and retained `\pon` / `\chaptergroup` semantics for entity pages and navigation grouping.
- Replaced fragile regex-only custom-macro argument parsing with balanced-brace parsing for up to eight arguments, so nested formatting in long feat/action/item/stat-block descriptions is preserved.
- Added a **PF2e** insert menu to the GM editor with ready-to-fill feat, action, item, monster, stat-line, and action-symbol snippets.
- Added regression tests for automatic XeLaTeX switching, persistent stale-engine cleanup, PF2e semantic cards/stat blocks, action symbols, legacy image helpers, and chapter-group navigation.

## 1.2.0

- Added Codex Studio art direction for table-of-contents covers/thumbnails, entry heroes, full-page backgrounds, focal points, article layouts, featured entries, and public/teaser/hidden discovery states.
- Added automatic TOC artwork fallback from the first image already present in an entry; manual art always overrides it.
- Added the editor **Artwork** composer with center/left/right/wide/breakout/full-bleed/portrait/banner/edge/watermark layouts, opacity, focus, blend modes, frames, captions, and parallax while preserving ordinary LaTeX figures for PDF/Overleaf.
- Added **Scene** panels: web-only atmospheric background wrappers around selected normal LaTeX prose, with tone, focus, strength, height, and parallax controls.
- Added conservative automatic cross-linking of unique codex names, related lore, backlinks, and a player-facing pan/zoom **Lore Network** graph.
- Added heading permalinks and an On-this-page scroll-spy navigator for long entries.
- Fixed the player codex sidebar resetting on entry navigation by preserving open groups, scroll position, and clicked-row viewport position across page loads.
- Added player-side bookmark/recent-reading trail and copyable page links.
- Added quick Open player page / Copy link controls to Codex Studio.
- Added **Build Doctor** recovery for stale `latexmk` failed-build caches, automatic auxiliary-state repair, direct-engine diagnostic fallback, and actionable compile suggestions. This specifically addresses the `Nothing to do for main.tex` + `pdflatex: gave an error` failure mode.
- Added regression tests for scene panels, automatic TOC imagery, automatic links/backlinks, and stale-latexmk diagnosis.

## 1.1.0

- Fixed responsive conversion of `longtable`, `tabular`, `tabularx`, and `tabulary`, including complex paragraph-column declarations.
- Added first-class `\pon{...}` Person-of-Note article grouping, Profile metadata grids, and TikZ-overlay portrait handling.
- Improved `\includegraphics` layout, asset lookup, captions, portrait/landscape/panorama inference, and image lightbox viewing.
- Made map `cover + edge lock` the strict default for both player and GM map cameras so empty space cannot be panned into view.
- Reworked marker authoring with an explicit placement crosshair, searchable marker directory, click-to-focus behavior, and removed accidental double-click placement.
- Added a searchable player location list alongside marker-category filters.
- Expanded the fantasy atmosphere system to 38 toggleable options and 16 presets, including god rays, valley mist, blizzards, heat haze, wave crests, shooting stars, petals, bats, dragon shadows, spectral wisps, cursed miasma, rune pulses, spores, blood moon, and fogged edges.
- Retains the v1.0.1 low-disk-space ZIP import fix.

## 1.3.5 — truthful engine diagnostics

- Fixed a Build Doctor false positive where any later fatal TeX error could be incorrectly attributed to `fontspec`/pdfLaTeX even while XeLaTeX was actually active.
- Font warnings now require an explicit "font not found" diagnostic; generic `fontspec` errors are no longer mislabeled as missing fonts.
- Build Doctor now compares the engine Seeker selected with the TeX engine banner actually observed in the log and reports project-local `latexmkrc` overrides when they disagree.
- Bumped static asset cache keys so Railway/browser caches cannot keep an older admin UI that lacks the **FIRST BLOCKING ERROR** panel after an application update.

## 1.3.7 — Atmospheric navigation backgrounds
- Restored first-image navigation artwork as the default, but as a full darkened row background rather than the old small thumbnail icons.
- Explicit Table-of-Contents artwork still overrides the automatically discovered first image.
- Added **Project → Use the first image as navigation background by default**, enabled by default and persisted per campaign.
- The setting affects both Codex overview entry rows and the desktop in-article Codex sidebar; disabling it returns navigation to text-only unless deliberate TOC art was assigned.
- Automatic navigation backgrounds use a dedicated presentation field, so they do not unexpectedly turn first-entry images into Lore Network thumbnails or deliberate chapter-cover artwork.
- PF2e action/reaction glyphs from `Images/Symbols` are skipped when choosing the automatic background, avoiding giant one-action icons when an entry begins with a rules block.

### 2.1.0 final visual QA
- Fixed the Lore Network heading/tools being hidden underneath the fixed site header on desktop and phone layouts.
- Campaign Control navigation now keeps readable labels on touch devices instead of degrading into an unexplained icon-only strip.
- Restyled World Builder calendar/geography/create-lore form controls so they remain dark, cohesive, and touch-friendly instead of using browser-default white inputs.
- Reflowed the phone Campaign Studio header into a clean two-row layout so workspace tabs, Compile, and editor pane controls stay reachable without crowding each other.
- Re-verified desktop (1440×900), iPad (1024×1366), and phone (390×844) shells for horizontal overflow and sticky navigation behavior.
