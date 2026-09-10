# Seeker 7.1.0 — Tempered

**Tempered** is a finish-and-flow release: it does not add another subsystem, but makes the existing Seeker surfaces faster, clearer and more trustworthy in daily play. Living Table, Monster Codex, Foundry Workshop, Encounter Builder, Knowledge, Table App, Asset Library, maps, permissions and campaign search now share a more consistent interaction language, clearer state feedback and stronger mobile ergonomics.

The most important reliability change is **live Foundry reconciliation**. HP, temporary HP, Hero Points, Focus and item quantities update optimistically in Seeker, follow the exact queued Foundry command through acknowledgement, and reconcile against the confirmed value without a full-page reload. The Foundry ACK also projects confirmed resource/quantity changes into Seeker's cached character snapshot immediately, closing the race where Foundry had already changed but Seeker still showed stale values until another refresh. Multiple rapid taps are tracked independently and failed writes roll back visibly.

Tempered also tightens PF2e Workshop validation before push, simplifies Token Forge through progressive disclosure, improves Encounter Builder budget legibility, makes Knowledge fidelity/certainty and effective permissions easier to scan, strengthens Foundry delivery-state presentation, improves Codex browsing and AoN batch confidence, makes relationship/front/change history easier to read, and reduces unnecessary work in hidden/reduced-motion maps. No new Foundry protocol is required; Foundry Bridge **1.7.0** remains current. Static/PWA cache generation is **7100**.

For the current Railway deployment the canonical public origin remains `https://seeker.up.railway.app`, with the Foundry module manifest at `https://seeker.up.railway.app/foundry/seeker-bridge/module.json`.

## Seeker 7.0.4 — Codex & Relay

**Living Table** turns the existing campaign wiki, session tools, Foundry Workshop, maps and world-state systems into one campaign operating layer. The canonical GM workspace is `/gm/living-table`; the phone-oriented player surface is `/app`. Existing Seeker data migrates additively and a pre-major-release SQLite backup is created automatically on first schema initialization.

For the current Railway deployment the canonical public origin is `https://seeker.up.railway.app`. Foundry Bridge **1.7.0** is installed/updated from `https://seeker.up.railway.app/foundry/seeker-bridge/module.json`.

This release focuses on trustworthy table operations: editable/removable Monster Codex entries, clean AoN imports, Discord mention verification, and persistent/observable Foundry delivery for HP, resources, item quantities and actor item grants.


## Seeker 7.0.3: Layered Knowledge & Party Deductions

Recall Knowledge and combat discovery now support **Exact**, **Vague**, and **Comparative** disclosure. A GM can keep the real statistic private while revealing qualitative or relative information such as “it is extremely vulnerable to fire” or “Fortitude is its highest save.” Disclosure is enforced server-side: player APIs receive only the chosen wording and never the hidden exact mechanics stored on the same knowledge fact. The Living Table knowledge panel lets the GM choose disclosure fidelity per fact both for direct reveals and for Recall Knowledge results, including an entire-party reveal target.

Players can now add **Field Deductions** to any visible entity. Notes may be private or party-shared, can represent freeform hypotheses/comparisons, or can track a numeric range such as an estimated AC. The AC helper can infer a range from a normal missed attack total and a normal hit total. Players can later share a private deduction with the party, and can also share a GM-revealed fact with everyone while preserving its original disclosure fidelity. Player deductions remain visibly marked as inference until a GM confirms or rejects them; they never silently become canonical monster mechanics.

The Table App and entity dossiers use the same player-safe projection, preventing exact creature summaries or knowledge metadata from bypassing Field Notes visibility. Static/PWA cache generation moves to **7030**. Foundry Bridge remains **1.6.0**; this release does not require a module update.

## Seeker 7.0.2: Archives of Nethys Creature Vault

The **Creature Vault** turns Archives of Nethys creature and NPC pages into normal Seeker monster entries. Paste one link or a batch of links, optionally publish them to the Monster Codex, attach them directly to an encounter, or organize them in reusable campaign collections. Seeker retains the canonical source link and stores the parsed creature fields rather than archiving the fetched webpage, keeping Railway storage small. Re-importing the same canonical AoN URL reuses the existing creature by default; **Refresh existing** deliberately refreshes mechanics while preserving Seeker artwork/token choices, GM notes and Codex visibility.

Encounter preparation and Creature Vault collections can now be pushed as a **single Foundry bundle**. Seeker Bridge 1.6.0 creates a real Actor folder for the encounter/collection, updates existing Seeker-managed actors when a UUID is already linked, creates missing actors, and reports failures per creature without discarding the rest of the folder. Imported AoN strikes support multiple damage components and imported statblocks may contain multiple spellcasting entries.

## Seeker 7.0.1: Proficiency Without Level encounters

The Living Table Encounter Builder supports both **Standard PF2e** and the official **Proficiency Without Level** encounter math. The rules mode is stored per encounter so old and new encounters remain reproducible. PWL uses the GM Core creature-XP table from party level −7 through +7 while retaining the normal encounter threat budgets and party-size scaling. Each creature row shows its calculated XP contribution, and an optional manual XP override is available for creatures outside the published PWL range instead of Seeker inventing values.

# Seeker — interactive setting & session companion

Seeker turns a normal multi-file LaTeX campaign project into **two synchronized views of the same setting**:

1. an Overleaf-style GM authoring workspace with a source tree, LaTeX editor, autosave, revision history, build log and live PDF preview; and
2. a polished player-facing interactive setting wiki with full-text + local semantic search, automatic chapter/section navigation and interactive maps.

It is designed for long-running Pathfinder 2e / TTRPG campaigns where the LaTeX project is already the canonical setting document, while Seeker becomes the shared companion players and GMs actually use between and during sessions.

## Seeker 6.1: Foundry bridge & table reliability

V6.1 turns the optional Foundry connection into a normal installable Foundry module. On the active campaign's **GM → Integrations** page, copy the manifest URL and paste it into Foundry's **Install Module → Manifest URL** field. Enable the module in the world, then paste Seeker's private bridge endpoint into the module settings. Only a GM Foundry client pushes data, and the bridge is read-only: Seeker never changes Foundry actors or scenes. The bridge now repairs reverse-proxy HTTP/HTTPS mismatches automatically and shows an in-Foundry success/failure notification after its first heartbeat, so a failed connection no longer leaves the GM with only an unexplained “Waiting for Foundry” state.

For the current Railway deployment, the canonical public origin is `https://seeker.up.railway.app`. Seeker normally derives this from the public request host (rather than blindly trusting a secondary Railway domain). You can still pin it explicitly with `SEEKER_PUBLIC_URL=https://seeker.up.railway.app`. Foundry Bridge 1.6.0 also repairs an old saved Seeker hostname after the module is updated from the current manifest.

Player characters can be linked to synced Foundry actors from the Seeker character editor. The owning player then gets a polished read-only PF2e sheet on Seeker with identity, vitals, defenses, skills, attacks, feats, actions, inventory, spells, conditions and a deep link back to the real Foundry actor. Foundry remains the source of truth; Seeker stores a bounded snapshot for display. Other players do not receive that private mechanical snapshot.

Discord integration can now store a campaign-specific mention (plain text or a real Discord role/user mention) and optionally post an automatic session-confirmation announcement when the GM first sets or changes a planned session date. V6.1 also fixes intermittent scroll trapping across normal pages, drawers and modal-heavy screens while keeping intentional fixed canvases such as Studio, Atlas and Table Display unchanged.

## Seeker 6.0: campaign continuity & integrations

V6 connects the systems Seeker already has rather than replacing them. It adds optional **Discord webhooks**, a small **read-only Foundry bridge**, private subscribable **calendar feeds / `.ics` exports**, rolling portable backups, campaign checkpoints/undo, Codex revision history, cross-campaign knowledge comparison and controlled campaign convergence. No external integration is required for normal use.

The **Continuity Center** shows what changed since the previous session, possible state contradictions, campaign knowledge differences, stored checkpoints and portable backups. The universal command palette can jump directly to table tools and offers GM-only actions such as advancing a named campaign clock or revealing a Codex entry.

For players, V6 adds a more useful campaign dashboard, private/party Atlas annotations and campaign travel history. For in-person tables, the GM gets a **Media Board** plus a token-restricted **Table Display** suitable for a TV or second monitor. Campaign archive export now produces a portable keepsake containing sessions, characters/milestones, objectives, discoveries, travel, mysteries, party notes, handouts, clocks and referenced local media.

All V6 integrations are additive and optional. Existing V5.1 campaigns, characters, sessions, availability, prep, lore, maps and player knowledge migrate in place.

## Seeker 5.1: GM runbook & stability

V5.1 turns **Session Prep** into a practical GM runbook rather than a long freeform note. A prepared session can now contain scene cards, movable clues/secrets, NPC quick cards, pacing guidance, consequences, campaign clocks, live event notes, reusable templates and random tables. **Improv Mode** collects useful NPCs, locations, unresolved material and random prompts when the party goes somewhere unexpected. The GM can push selected information to players without leaving prep.

At the end of play, the **Session Closeout** walks through the important state changes and can seed the next planned session from unfinished scenes, unresolved clues, objectives, mysteries, fronts, character arcs and pending consequences. A private Continuity Check and spotlight reminder help the GM notice loose threads; spotlight information is strictly GM-only and is never shown or announced to players.

V5.1 also repairs the reported V5 regressions: Session Prep scrolls normally again, narrative character dossiers render in a bounded responsive layout, Atlas markers reliably open their detail drawer, and notification read state persists for the GM across navigation. Players may dismiss notifications for themselves, while the GM can delete a notification globally.

## Seeker 5.0: the session companion

Seeker V5 is built around one division of responsibility: **Seeker remembers the campaign; Foundry and Pathbuilder handle the rules engine.** Character pages therefore focus on identity, story, goals, portraits, relationships, arcs, milestones and links to the real mechanical sheet rather than maintaining a second PF2e build in parallel.

The centerpiece is **Session Mode** (`/session`). During in-person play it acts as a desktop/tablet command center; on iPad it uses a dedicated two-column layout; on phones it becomes a touch-first tabbed companion. It brings together the current character identity, collaborative party notes, private character notes, objectives, mysteries, handouts, followed lore, recent discoveries, recap context and Atlas shortcuts without forcing players to bounce through the whole site.

GMs prepare through **Session Prep** (`/gm/prep`). A planned session can have an opening, ordered scene/beat checklist, secrets and revelations, contingencies, scratch notes and pinned references to Codex lore, objectives, character arcs, mysteries, fronts, handouts and maps. The prepared runbook follows the session into the GM live console, so prep is not stranded in a separate notebook.

V5 also adds a private player **Investigation Board**, campaign objectives, lore follows/watches and notification preferences, a data-grounded **Previously on…** briefing, narrative character milestones, session RSVP, and campaign-specific Atlas knowledge/fog. Session scheduling remains player-global: availability is filled once per player and reused across every campaign in which that player has a current character.

Multi-campaign management now supports true permanent deletion of non-default campaigns. Deletion removes table-specific state while preserving shared setting canon, player identities and global availability. The default campaign is intentionally protected.

The free local semantic Codex search from V4 remains available and spoiler-safe; it does not require an API key or hosted AI service. Optional OpenAI-compatible answer generation can still be configured separately if desired.

## What it does

- **Edit LaTeX in the browser.** `/admin` is a private GM workspace.
- **Live formatting feedback.** Saving updates the player-wiki preview; after a short idle delay Seeker compiles the real LaTeX project and refreshes the PDF preview.
- **Import your existing Overleaf project.** Upload the Overleaf source ZIP from the Project tab. Seeker backs up the existing project first.
- **Keep your Overleaf workflow if you want it.** Export the entire current project as a ZIP at any time and upload it to Overleaf again.
- **Understands project structure.** It detects the likely main `.tex` file, resolves `\input{}` / `\include{}`, preserves chapters/sections/subsections, inspects `\newcommand`, custom environments, packages, colors, and `\includegraphics` references.
- **Fails gracefully on unusual LaTeX.** Unknown commands are unwrapped so their human-readable arguments are not silently discarded. Custom macros whose names look like NPC/location/lore-box commands are rendered as callouts in the wiki. `\pon{...}` is treated specially as a Person-of-Note article root, so its Profile/Biography subsections stay together instead of becoming unrelated wiki pages.
- **Understands campaign-book layouts.** `longtable`, `tabular`, `tabularx` and `tabulary` are converted to responsive HTML tables without leaking TeX column declarations such as `>{\raggedright}p{3.5cm}` into player text. `multicols` profile blocks become compact metadata grids.
- **Smart imported images.** `\includegraphics` assets are resolved even when extensions are omitted or assets live below graphics folders. Figure/wrapfigure layouts, PDF graphics, captions and common TikZ page-overlay portraits are translated to web-friendly layouts. Players can click rendered images for a full-resolution lightbox, and portrait/landscape/panorama treatment is inferred from the actual image dimensions.
- **Compiles the original PDF.** The Docker image includes `latexmk`, pdfLaTeX, XeLaTeX, LuaLaTeX, common LaTeX-extra packages, fonts and graphics packages. Project-local `.cls` and `.sty` files work normally.
- **Codex Studio / art direction.** Every chapter and entry can have its own table-of-contents artwork. Entries can additionally have a cinematic hero, full-page background, focal point, background strength, article width, feature status, and public/teaser/hidden discovery state. By default, the first meaningful image found inside a chapter becomes the darkened atmospheric background of the **whole large chapter/section block** in the Codex. Individual entry headlines and the article sidebar remain clean and text-only. Deliberate chapter artwork overrides the automatic image, and the automatic section backgrounds can be switched off globally in Project settings.
- **Free-form web artwork without giving up LaTeX.** The **Artwork** tool inserts an ordinary `\includegraphics` figure for the PDF plus a harmless `% seeker-image:` comment for the wiki. Layouts include centered, floating left/right, wide, breakout, full-bleed, portrait, banner, decorative edge art, and watermark, with independent width, opacity, crop focus, blend mode, frame, caption, and parallax controls. Existing automatic image handling still works when you do not add a directive.
- **Atmospheric scene panels.** Select any normal LaTeX prose and press **Scene** to place that passage over an image in the player wiki. The source remains valid ordinary LaTeX because Seeker stores the web presentation as comments around the selected text. Scene tones include dark, light, sepia, arcane, mist, and blood, with focus, image strength, height, and optional parallax.
- **Living lore connections.** Unique codex names mentioned naturally in prose can be cross-linked automatically (optional in Project settings), explicit `\wiki{}` links remain supported, and pages show related lore/backlinks. The **Lore Network** player view turns these relationships into a pan/zoom interactive graph with artwork-backed nodes.
- **Long-entry navigation.** Section/subsection headings receive stable deep links and long articles get an **On this page** navigator with scroll tracking. Player bookmarks/recently viewed entries form a private browser-side reading trail.
- **Stable codex sidebar.** Opening another entry no longer throws the player back to the top of the navigation. Seeker remembers expanded chapter groups, scroll position, and the clicked row position across full page navigation.
- **Build Doctor.** `latexmk` stale-failure states are detected and repaired automatically, the underlying TeX engine is invoked for a diagnostic pass when `latexmk` only returns a wrapper summary, and the editor surfaces likely fixes rather than only showing `pdflatex: gave an error`. High-confidence source mistakes can be repaired individually or with **Apply all safe fixes**; the full batch is verified before any source is changed and every affected file is revision-backed. Repeated `geometry` package declarations can be consolidated automatically. When TeX returns errors but still creates a fresh PDF, Seeker keeps that recoverable preview visible while clearly marking the build as not clean.
- **Native PF2e campaign mechanics.** Your existing `\feat`, `\action`, `\itemtemplate`, creature/stat-block commands, action-symbol macros, `\chaptergroup`, `\pon`, and legacy `\image` helper remain authoritative LaTeX for the PDF while receiving dedicated responsive Codex rendering. Nested arguments are parsed safely, and the editor has a PF2e insertion palette for creating new entries with the same command vocabulary.
- **Interactive atlas.** Upload a map image, enter explicit **＋ Location** placement mode, follow the placement crosshair, click once to place a marker, drag markers into position, attach descriptions and link them to codex pages. A searchable marker directory makes existing locations easy to find/focus. Player maps also expose a searchable location panel and category filters. Markers can be player-visible or GM-only and use a broad icon library for settlements, ports, fortifications, roads, terrain, institutions, commerce, hazards, monsters, secrets, temples, portals, quests, and more. Large/high-resolution source maps automatically receive a stronger atmosphere scale so visual effects remain readable on 4K artwork.
- **Edge-locked map navigation.** Player maps use a cover-style minimum zoom by default: when you pan, the map cannot be pushed past the viewport and reveal empty space beyond its edges. Wheel, buttons, and touch pinch all zoom around the pointer/fingers.
- **Fantasy atmosphere studio.** Per-map switches include moving clouds, cloud shadows, rolling fog, valley mist, god rays, rain, lightning, snow, blizzards, ashfall, sand/dust, heat haze, ocean shimmer, moving wave crests, embers, fireflies, pollen, leaves, petals, birds, bats, rare dragon shadows, arcane motes, spectral wisps, cursed miasma, ley lines, rune pulses, glowing spores, aurora, stars, shooting stars, vignette, fogged edges, parchment warmth, moonlight, blood-moon tint, cartographer grid, and compass rose. Presets now include Calm Fantasy, Stormbound, Frozen North, Haunted Realm, Arcane Night, Volcanic Wastes, Ancient Parchment, Coastal Breeze, Autumn Road, Feywild Glade, Scorched Desert, Underdark, Blood Moon, Ancient Ruins, Blighted Realm, and High Fantasy.
- **Revision safety.** Seeker keeps up to 40 saved revisions of each file edited in the browser.
- **Personal player invitations.** Player access is invitation-only by default. **Admin → Access** creates one signed link per player; each link can be copied, expired, revoked, restored, rotated, device-limited, or have its remembered devices reset independently. Legacy shared-password and public modes remain available, while the editor continues to use `ADMIN_PASSWORD`.
- **Read → edit source bridge.** When you browse the player Codex while logged in as GM, a persistent **Edit source** control opens the exact LaTeX file/line in Campaign Studio. On long Person-of-Note pages it follows the section currently being read, and the editor offers **Back to entry** after the correction.

## Seeker 4.4: player feedback, richer characters, and free semantic search

Seeker 4.4 is a table-use polish release built from the first round of player feedback. **Relationships** are now searchable/filterable rather than an endless list, touch scheduling favors scrolling over painting, comments and characters have permission-aware deletion, GMs can maintain player character sheets, and the campaign selector includes a clear **All Tables** view. Atlas authoring has a much larger marker vocabulary and its atmospheric renderer compensates for high-resolution/4K map sources.

V4.4 briefly introduced a rules-heavy character builder. V5 intentionally retires that visible workflow in favor of lighter narrative dossiers plus Pathbuilder/Foundry links, while retaining old stored sheet data so upgrades are non-destructive. GMs retain edit/delete access for table administration.

Search now includes **local semantic retrieval with zero API cost**. Seeker builds a compact in-process index from the Codex a player is actually allowed to see and combines lexical scoring, generic concept expansion and relationships learned from terms that co-occur in the setting. A question like “who rules the northern realm?” can therefore find an entry that says “King Vael holds the crown” even when the exact wording differs. Because the source set is the already spoiler-filtered Codex, semantic retrieval cannot surface hidden pages. The index cache is bounded to keep Railway memory predictable. Optional OpenAI-compatible answer generation is still supported through `SEEKER_AI_API_KEY` / `SEEKER_AI_MODEL`, but is not required for semantic finding.

The schedule remains deliberately **player-global**: rows are stored only by invitation + date. Adding a second character or joining a second campaign never moves or duplicates availability. Each campaign simply asks which unique players currently have active characters there and reads those same player-level dates.

## Seeker 4.3: session planning across campaigns

Seeker now includes a dedicated **Session Planner** at `/schedule`. Availability is attached to the invited player identity rather than to a character or campaign: a player marks each date once as **Available**, **If necessary**, or **Unavailable**, and that single calendar automatically follows every current character they have assigned to a campaign.

The GM planner uses the active campaign’s character roster to determine who belongs at that table, deduplicates players who have multiple PCs, and highlights the earliest fully green date. If no all-green date exists, it separately surfaces dates that work only because one or more players selected **If necessary**. Unanswered dates remain unknown and never produce a false “everyone is free” result. Players can paint/drag dates and use quick fills; writes are batched and there is no schedule polling.

Character creation includes an explicit campaign selector, matching the intended flow: **GM creates campaign → player creates/assigns character → player fills availability once → GM checks the campaign planner**. Character assignment is the scheduling source of truth; availability itself never moves between campaigns. Revoking the player invitation globally still removes that player from scheduling.

## Seeker 4.2: one setting, multiple campaigns

Seeker can now host several active campaigns inside the same world. The **Codex, Atlas and setting history remain shared**, while table-specific state stays isolated. A player who plays Aster in one campaign and Bram in another sees the correct character shelf, session history, journals, mysteries, handouts, threads and spoiler knowledge after switching tables.

The owner manages campaigns in **Worldcraft → Campaigns**, where each campaign can be named, archived, made the default, and assigned its own set of player invitations. Existing installs are migrated safely into a **Main Campaign**, so upgrading does not require reconstructing the party by hand.

## Seeker 4: player-first sessions + table QoL

Seeker 4 focuses on reducing the little bits of friction that interrupt actual play. The main player destinations stay obvious, session bookkeeping understands which PC somebody is playing, and first-time users no longer have to discover the interface by trial and error.

- **Enter a session as a character:** if an invited player owns multiple PCs, Player Session asks which one they are playing tonight. A player can also explicitly enter without a character scope. The choice is tied to the current live session rather than becoming a permanent account setting.
- **Character-scoped session journals:** private/party journal entries can belong to a specific PC. Switching from one of your characters to another hides the first character's personal notes while retaining explicitly player-wide notes. Older journals are migrated as player-wide so upgrades do not lose or misassign existing writing.
- **Safer ownership boundaries:** the backend validates character ownership on journal writes rather than trusting browser-submitted IDs.
- **Faster note-taking:** unfinished new journal entries are locally draft-saved and restored; campaign journals can be filtered by character; session references display useful session numbers/titles rather than opaque IDs.
- **Calmer desktop navigation:** the permanent bar keeps Codex, Session, Campaign, Characters and Atlas prominent. History, Calendar, Mysteries, Lore Network, Families & Orders, Handouts and release notes move into **Explore**; Studio/World/Living/GM Session move into a compact **GM** menu for authorized users.
- **Quick Tour for everyone:** a short role-aware onboarding tour runs once on first use and can be replayed from the UI whenever somebody needs a refresher. Player steps emphasize Session, Characters, Campaign, Search and discovery; GM steps emphasize the authoring/session-control workflow.
- **Useful search before typing:** opening Search immediately offers common destinations plus recently viewed lore, making it useful as a command palette during a session instead of only as full-text search.
- **PWA-safe upgrade:** v4 uses fresh static/cache versions and retains network-first static fetching so installed/home-screen clients do not get pinned to obsolete JavaScript after deployment.

## Seeker 3: living world + player agency

Seeker 3 deliberately separates **authored lore** from **campaign state**. Your `.tex` files remain the durable setting manuscript; fast-changing table state lives in the database where it can evolve session by session without turning a 300+ page book into application metadata.

The central design rule is: **give players agency where bookkeeping benefits from shared ownership, while keeping canonical lore and secrets under GM control.**

- **Player/party-maintained plot threads:** players can create and maintain quests, mysteries and unresolved plotlines, add their own notes/clues/theories/questions, and link them to lore. Threads may be player-owned, party-editable or GM-owned. Note authorship is retained, so collaboration does not mean another player can silently rewrite someone's personal note. The GM can always supplement or correct shared state.
- **Per-player knowledge:** the GM can track whether each player knows, suspects, has heard a rumor about, or has not discovered a lore/state target. Spoiler-aware views use that knowledge rather than assuming the entire party knows the same things.
- **Living-world Fronts:** factions, threats, wars and projects can advance clocks and log off-screen moves between sessions.
- **Dynamic NPC/entity state:** current location, status, attitude, faction, objective and last appearance are runtime facts, separate from historical biography.
- **Changing relationships:** semantic relationships can have historical periods; family trees and organization charts get specialized hierarchy data instead of being forced through the general Lore Network.
- **Historical cartography:** draw region polygons and dated border variants so political/geographic regions can change across the Chronicle.
- **Rumors:** author location/faction-specific hearsay with hidden truth classification, then reveal only the rumor text to players.
- **Player journals and character arcs:** invited players maintain private/party session journals, character promises/goals, arcs and character relationships themselves.
- **Submissions rather than canonical edits:** players can submit setting ideas, recaps and relationship proposals for GM review without touching LaTeX source.
- **GM Inbox:** capture notes, photos, reminders and voice memos during play, then organize them after the session.
- **Staged publishing + live discoveries:** prepare lore privately, publish related changes together, and surface discoveries/spotlights on the player Session screen.
- **Media Library:** tag portraits/maps/crests/handouts/backgrounds, set focal points/alt text, find every usage and (owner-only) replace references globally.
- **Continuity + provenance:** detect likely contradictions between mutable state and authored lore, keep session-state snapshots, and retain where/when major lore appeared.
- **Roles:** Owner, Co-GM, Player, Observer and Guest. Co-GMs can operate campaign-state tools without receiving owner-only infrastructure/export control; observers and guests stay read-only.
- **Portable backup + archive mode:** export source + uploads + database + manifest in one archive, integrity-test it before relying on it, and freeze a completed campaign into a read-only archive.
- **Foundry export:** send journals/characters outward without trying to replace Foundry's PF2e combat automation.

The GM control center is `/admin/living`; the player-facing campaign hub is `/campaign`, with collaborative threads at `/campaign/threads`.

## Seeker 2.1: worldbuilding and party workflows

Seeker 2.1 focuses on the parts of v2 that should feel effortless at the table and during prep:

- **Readable Lore Network:** the default Story view is deliberately selective. Explicit relationships and entity-centered references are kept; generic heading-to-heading noise is capped. Labels appear only where useful, selecting a node isolates its neighborhood, and touch users can pan and pinch-zoom naturally. **Curated relationships** shows only GM-authored semantic links; **All references** remains available when you really want the complete graph.
- **Historical Chronicle:** History is organized into named eras with start/end dates, summaries and visual accents. Historical events support type, date ranges, significance, certainty, related Codex lore and player/GM visibility. Session recaps live in Session Mode rather than pretending to be world history.
- **Visual World Builder:** months, weekdays and moons use structured editors instead of pipe-delimited text fields. Geography/travel values, lore creation, history, people/factions and maps are presented as task-oriented panels.
- **Create real lore from a template:** choose Person, Settlement, Faction, Deity, Historical Event, Creature or Handout, name it, and press **Create entry in Campaign Studio**. Seeker creates an ordinary `.tex` file under `Worldbuilding/`, inserts its `\include{}` into the canonical main source, and opens it in the editor.
- **Tabbed Campaign Studio:** source files open in a reusable tab strip rather than replacing the only editor buffer or opening extra browser windows.
- **Phone/iPad GM navigation:** Player, GM Session, Studio and Campaign Control are always reachable through persistent mode controls. iPads/tablets use touch-sized single-pane editor switching instead of a cramped desktop layout.
- **Player Characters:** invited players can create more than one character, maintain their own profiles/biographies/goals, upload portraits and inspiration art, retire old PCs, and decide whether each character is party-visible or private to themselves and the GM. Character search and mobile navigation make the party shelf easy to reach during play.

## Seeker 2: run the campaign from the wiki

Seeker 2 adds a campaign-runtime layer on top of the LaTeX/PDF workflow rather than replacing it. The canonical source remains ordinary LaTeX, while the live site can now change what each invited player knows and what the table is currently focused on.

- **GM Session Mode:** start/end sessions, spotlight relevant lore and maps, reveal secrets, send discoveries, and surface handouts from a touch-friendly session dashboard.
- **Player Session Mode:** a phone-first table screen with current location, spotlight lore, live discoveries, open mysteries, handouts, and previous-session recaps.
- **Progressive lore:** select prose in the editor and press **Reveal** to create a web-only hidden/rumor/discovered/public block. Audience and expiry controls live in Campaign Control / GM Session Mode.
- **Timeline + world calendar:** maintain eras, wars, reigns, discoveries, festivals, custom months/weekdays/moons, seasons, and the current in-world date.
- **Mystery boards:** pin clues and connect them with editable red-string relationships. Player boards render only clues and connections the player is allowed to know.
- **Relationships and dossiers:** explicit `member of`, `worships`, `located in`, `enemy of`, etc. relationships feed profiles, backlinks, hover previews and the Lore Network; aliases redirect alternate names to the canonical entry.
- **Notes and reading history:** players can keep private/party notes and bookmarks while the GM can keep private margin notes. Recent-reading and newly-discovered feeds help players return after a session.
- **Handouts:** letters, parchment documents, newspapers, wanted posters, journals and visions can be delivered independently or attached to a session.
- **Atlas layers + discovery fog:** overlay political/road/trade/religion/etc. layers, reveal regions as the party explores, and estimate map travel between discovered markers.
- **Campaign Control:** health checks, snapshots/restore, templates, world settings, lore styling, session history and campaign state live in one GM workspace.
- **Phone/iPad/PWA:** the player site has a bottom-tab mobile UI, touch Atlas controls and responsive reading/session layouts. The GM editor becomes Files / Editor / Preview panes on small screens. iPhone/iPad: Safari → Share → **Add to Home Screen**. Android/Chrome: **Install app** / Add to Home Screen.

The editor's top application bar is persistent while working in long files, and the GM can still jump from a typo in the player Codex directly to the exact `.tex` source line and back.

## Repository layout

```text
seeker/
├─ app/                 FastAPI backend, LaTeX parsing, compilation, maps, storage
├─ campaign/            first-run seed project; replace/import from the editor
├─ static/              editor, wiki, and animated-map frontend
├─ templates/           player and admin HTML
├─ tests/               parser/storage regression tests
├─ Dockerfile           Railway/local production image
├─ railway.toml         health check + Docker build config
└─ requirements.txt
```

## Railway deployment

### 1. Push this repository to GitHub

Create a normal GitHub repository from this folder and push it.

### 2. Create the Railway service

In Railway, create a service from the GitHub repo. The root `Dockerfile` is detected automatically. The service listens on Railway's injected `$PORT` and exposes `/health` as its health check.

### 3. **Attach a persistent volume at `/data`**

This is the important step for wiki-first authoring. Your editable LaTeX project, revision history, compiled artifacts, maps and SQLite metadata live under `/data`.

Without a volume the app still runs, but browser edits live on the service's ephemeral filesystem and can disappear on a redeploy.

### 4. Set variables

At minimum:

```text
ADMIN_PASSWORD=<a strong GM password>
```

Optional:

```text
# Only needed if you deliberately switch Admin → Access to Shared Password mode:
PLAYER_PASSWORD=<legacy shared player password>
LATEX_ENGINE=auto           # recommended; also accepts pdflatex / xelatex / lualatex
LATEX_TIMEOUT=60
LATEX_ALLOW_SHELL_ESCAPE=0

# Optional: only if you want generated Ask Seeker answers.
# Local semantic search works without these.
SEEKER_AI_API_KEY=<OpenAI-compatible API key>
SEEKER_AI_MODEL=<model name>
SEEKER_AI_BASE_URL=https://api.openai.com/v1
```

The default player gate is **Invitation links only**, so normal deployments do not need `PLAYER_PASSWORD`. After logging into `/admin`, open **Access**, create one invitation for each player, and send each player their own link.

If `ADMIN_PASSWORD` is omitted, Seeker generates one on first startup, stores it in `/data/.admin_password`, and prints it to the service logs. Setting the variable explicitly is cleaner.

### 5. Open `/admin`

Import the ZIP downloaded from **Overleaf → Download → Source**, or simply start editing the included sample project.

GitHub remains the deployment source for the *application*. Your live campaign source is persistent data inside Seeker, so updating the application does not require manually copying the campaign PDF anywhere.

## Local development

### Easiest Windows path

With Docker Desktop installed, double-click `start_local.bat`. The service binds only to `127.0.0.1`, stores its campaign in a named Docker volume, and uses `seeker` as the local-only editor password unless you set `ADMIN_PASSWORD`.

### Docker

```bash
docker build -t seeker .
docker run --rm -p 8000:8000 \
  -e ADMIN_PASSWORD=dev-password \
  -v loreforge-data:/data \
  seeker
```

Open:

- Player wiki: <http://localhost:8000/>
- GM editor: <http://localhost:8000/admin>

### Python development without Docker

You need a local LaTeX distribution containing `latexmk` plus your chosen engine.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

# Point data somewhere writable for development.
# PowerShell: $env:DATA_DIR="$PWD/.data"
# bash/zsh:
export DATA_DIR="$PWD/.data"
export ADMIN_PASSWORD="dev-password"

uvicorn app.main:app --reload
```

## How the LaTeX → wiki conversion works

Seeker deliberately does **not** replace TeX as the authoritative PDF renderer. The PDF preview is generated by your actual LaTeX engine. The player wiki is a semantic companion view.

The converter:

- chooses the main file using stored settings and common names (`main.tex`, `book.tex`, `campaign.tex`, `setting.tex`, `world.tex`), then scores remaining candidates by `\documentclass`, `\begin{document}`, `\input`, and `\include` usage;
- recursively resolves included `.tex` files while preventing path traversal;
- uses `\part`, `\chapter`, `\section`, `\subsection`, and `\subsubsection` to build the codex;
- understands common inline formatting, lists, quotations, links and images;
- converts `longtable`, `tabular`, `tabular*`, `tabularx`, and `tabulary` into responsive HTML tables while consuming TeX column specifications such as `>{\raggedright}p{3.5cm}` so they never leak into prose;
- treats `\pon{Name}` as a Person-of-Note article root: following Profile/Biography sections stay in one article, label/value `multicols` profiles become structured metadata grids, and common TikZ-overlay NPC artwork becomes responsive portrait art;
- interprets common image intent (`figure`, `wrapfigure`, TikZ overlay art, `width`, `scale`, portrait/panorama aspect ratio) and keeps full-resolution click-to-zoom;
- detects custom `\newcommand` definitions and preserves their argument content;
- renders macros with names resembling `npc`, `character`, `location`, `place`, `lorebox`, `note`, etc. as richer wiki callouts;
- records unresolved images and discovered packages/macros in **Project → Formatting analysis**.

This is intentionally tolerant. A campaign with a giant custom `.cls` file should still produce useful lore even when the HTML renderer does not know every visual TeX primitive.

### Pathfinder 2e rule/stat-block macros

Seeker has native web renderers for the campaign commands you supplied. Your definitions remain unchanged and continue to control the PDF; Seeker only recognizes their *usage* when building the player Codex:

```latex
\feat{Name}{Level}{Traits}{Description}
\action{Name}{\actionOne}{Traits}{Description}
\itemtemplate{Name}{Item 5}{Traits}{Description}

\begin{monster}{Creature Name}{Level}{Traits}{Source}
  \monsterline{Perception}{+12; darkvision}
  \monsterabilityscores{+4}{+3}{+2}{+0}{+2}{-1}
  \monsterdefenses{21}{Fort +13, Ref +12, Will +10}{HP 75}{Resistance 5 fire}
  \monsterspeed{30 feet}
  \monstersection{Offense}
  \monsterattack{Melee \actionOne jaws}{15}{reach 10 feet}{2d8+7 piercing}
  \monsterability{Special Ability}{Rules text.}
\end{monster}
```

The player site renders these as responsive Pathfinder-style rule cards and creature stat blocks instead of flattening the four/six-argument macros into prose. `\actionOne`, `\actionTwo`, `\actionThree`, `\reaction`, and `\freeAction` use the images in `Images/Symbols/` when those files exist. `\image{0.5\textwidth}{Images/foo.png}` is also recognized as an image helper.

The GM editor now includes an **PF2e** button beside **Artwork** and **Scene**. It inserts ready-to-fill feat, action, item, monster, stat-line, and action-symbol snippets using these existing commands.

Custom commands that Seeker does not know explicitly are now parsed with balanced braces for up to eight arguments, so nested `\textbf{...}`, `\emph{...}`, links, and other formatting inside long arguments are not discarded.

### Optional explicit wiki links

Seeker recognizes:

```latex
\wiki{Temple of the Eternal Flame}{the old temple}
```

The PDF fallback macro can be defined in your source however you like, for example:

```latex
\newcommand{\wiki}[2]{#2}
```

In the player wiki, this becomes a link to the matching slug.

## Invitation-only player access

Open **Admin → Access**. Seeker defaults to **Invitation links only**. Create one link per player with a recognizable label such as `Sarah` or `Piotr`. Opening that private URL establishes a signed Seeker session in that browser and sends the player directly into the campaign—there is no shared player password.

Each invitation shows its state, expiry, last-used time, invitation-open count, and remembered browser/device count. When creating a link you can optionally cap it to 1–5 devices in the UI (the backend accepts up to 20). From the same screen you can:

- **Copy link** again at any time;
- **Revoke** it, immediately invalidating browsers authenticated through that invitation on their next protected request;
- **Replace / rotate** it, invalidating the old URL and all sessions from the previous version and clearing remembered devices;
- **Reset devices** without changing the URL, useful after a player changes phone/browser; existing sessions stop working until the player reopens the link;
- open/test an invitation while logged in as GM without consuming one of its player device slots;
- **Restore** a revoked, non-expired invitation;
- set an expiry when creating a link; and
- permanently delete old invitation records.

Invitation tokens are signed with Seeker's persistent session secret and versioned per player. There is no global player secret to share, and the GM password is never placed in an invitation URL. As with any bearer link, a player can still forward their personal URL to someone else; a low device limit reduces casual sharing but is not identity verification. Treat the URL like a password and revoke/rotate it if it leaks.

Two fallback modes exist for unusual deployments: **Shared Password** uses the legacy `PLAYER_PASSWORD` environment variable, and **Public** removes the player gate entirely. Creating a new personal invitation automatically switches the site back to invitation-only mode.

## GM read → edit source bridge

Open the player site from the same browser where you are logged into `/admin`. Codex entries then show an unobtrusive GM-only **Edit source** button plus a floating edit control that remains available while you scroll. Clicking it opens Campaign Studio at the corresponding `.tex` file and line. On long entity pages such as `\pon{...}` entries, Seeker retains the source line for nested Profile/Biography/etc. headings, so the floating control follows the section currently in view.

The editor URL uses `?file=...&line=...&from=...`; CodeMirror jumps to the requested line and the top bar shows **Back to entry**. This makes quick spelling/lore corrections a read → edit → return workflow rather than a manual file-tree search.

## Codex Studio and art direction

Open **Admin → Codex Studio** and select either a chapter or a specific entry.

For a **chapter**, assign a table-of-contents cover. For an **entry**, you can independently assign:

- table-of-contents thumbnail;
- hero/banner artwork;
- full-page background artwork;
- cinematic banner, split, portrait-panel, or minimal hero style;
- standard, wide, or cinematic article width;
- background opacity and X/Y focal point;
- featured-home-page status;
- public, teaser, or hidden discovery state.

For large chapter/section blocks, Seeker can automatically use the first usable image rendered inside one of that chapter's entries. The Codex Studio chapter inspector labels this `AUTO · SECTION BACKGROUND`, so you can tell the automatic section treatment from manually curated artwork. A manually chosen chapter image always wins. Entry-level artwork remains deliberate and is not automatically painted behind individual navigation headlines.

The editor toolbar has two complementary tools:

### Artwork

**Artwork** inserts a standard LaTeX `figure` plus a web-only comment. The PDF therefore remains portable to Overleaf, while the wiki can use richer responsive placement:

Seeker also continues to understand the older `loreforge-*` comment directives, so existing campaign sources do not need a migration.

```latex
% seeker-image: layout=edge-right width=34 opacity=0.80 blend=soft-light frame=none
\begin{figure}[htbp]
  \centering
  \includegraphics[width=.34\linewidth]{Images/sigil.png}
\end{figure}
```

You can also use `watermark`, `fullbleed`, `breakout`, `banner`, `portrait`, `left`, `right`, `edge-left`, and the ordinary automatic layout. If you never use these comments, all pre-v1.2 automatic figure/portrait behavior remains active.

### Scene

Select a paragraph, quotation, subsection introduction, or other ordinary LaTeX and press **Scene**. Seeker wraps it like this:

```latex
% seeker-panel-start: image="Images/Places/stormgate.jpg" opacity=0.38 x=65 y=42 tone=arcane min_height=360 parallax=true
The gate wakes only when both moons stand above the eastern sea.
% seeker-panel-end
```

TeX sees two comments plus the unchanged prose. The player wiki renders the same passage as an atmospheric image-backed scene. This is useful for chapter openings, dream sequences, major reveals, cities, dungeons, gods, and historical interludes.

## Lore relationships

Seeker can automatically link the first natural mention of a **unique** codex entry name in another article. It deliberately ignores ambiguous duplicate titles and generic headings. Disable this globally with **Admin → Project → Automatically cross-link codex names in prose** if you prefer only explicit links.

Automatic and explicit links feed three systems:

1. **Related lore** suggestions on entries;
2. **Backlinks** showing which other entries refer to the current subject; and
3. **Lore Network** in the player navigation, an interactive visual graph of the setting.

This means the wiki becomes progressively more interconnected as the LaTeX source grows, without requiring a second manual relationship database.

## Build Doctor diagnostics

Every failed build shows a prominent **First blocking error** excerpt. This fallback is intentionally independent of the clickable file/line parser, so unfamiliar TeX/package failures cannot leave the editor at a generic “Compilation failed” state. **Copy diagnostic bundle** copies that excerpt, up to 20 structured errors, and the recent engine-log tail for troubleshooting.

### Automatic section-block backgrounds

The large Codex chapter/section cards are image-backed by default without bringing back the old tiny thumbnail icons. Seeker searches the entries inside each section for the first meaningful rendered image (skipping PF2e action symbols and other utility icons) and uses it as a darkened background across the **whole section block**. Individual entry headlines and the desktop article sidebar remain text-only. A manually chosen chapter **Table-of-contents artwork** image overrides the automatic section image. Disable **Project → Use the first image as section-block background by default** to return the large blocks to the plain treatment.

## Compile result verification

Seeker verifies the final PDF rather than trusting only `latexmk`'s process exit code. Some large XeLaTeX projects can finish `xdvipdfmx`, write a valid PDF, and still leave a non-zero wrapper status from an earlier rule. If the PDF is valid, no real TeX source error is present, and the build log explicitly confirms the final target (for example `All targets (main.pdf) are up-to-date`), Seeker treats the build as successful instead of showing a false `Compilation failed`.

## Compile status and large XeLaTeX projects

Seeker evaluates the **terminal** build state, not merely latexmk's process return code. This matters for large XeLaTeX books where an earlier pass may fail or be retried, while a later `xdvipdfmx` stage successfully writes the final PDF. If the final successful PDF witness occurs after all fatal markers, Seeker accepts the build and does not mislabel old diagnostics from an earlier pass as the current blocker.

For large campaign books, Seeker also avoids duplicating the finished PDF on the persistent volume. The canonical output remains beside the main `.tex` file and `/preview/pdf` serves it directly; `build/campaign.pdf` is only a zero-copy link when the host supports links. Upgrading from older versions automatically removes an obsolete full-copy preview when the canonical PDF still exists. This is important on small Railway volumes, where a 140 MB campaign PDF should consume roughly 140 MB, not roughly 280 MB merely to support the preview pane.

## Live editing behavior

- Browser changes autosave after roughly 0.7 seconds of inactivity.
- The player-wiki representation is rebuilt on save.
- The real LaTeX PDF compiles after a slightly longer idle delay, or immediately with **Compile** / `Ctrl+Enter`.
- `Ctrl+S` saves immediately.
- LaTeX build errors are shown in the Build Log tab; file/line diagnostics are clickable when the engine emits `file.tex:line:` diagnostics.

## Maps

Open **Admin → Maps**:

1. Create a map and upload PNG, JPG or WebP.
2. Press **＋ Location**, then click where the marker belongs. Double-click remains available as a shortcut.
3. Drag existing markers directly on the map to reposition them.
4. Choose a marker type, description, player visibility and optional codex page.
5. Open **✦ Atmosphere** to configure the map.
6. Choose a preset or independently toggle any of the fantasy layers. Intensity, animation speed, marker size/labels/pulses, viewport fit mode and edge locking are also configurable.
7. Press **Save map** to publish those settings to the player atlas.

### Map movement

The default player setting is **Edge-locked / cover**. Seeker calculates the minimum zoom needed to cover the viewport and clamps X/Y movement so the user can never pan beyond the physical map boundaries. This fixes the "floating map" behavior where a player could previously shove the image into one corner and expose empty background.

You can deliberately switch a map to **Show whole map / contain** from its Atmosphere panel. The map remains clamped, but letterboxing is allowed when the image and viewport aspect ratios differ.

### Fantasy atmosphere layers

All effects are browser-rendered overlays; the uploaded map file itself is never modified. Available switches include:

- Atmosphere: moving clouds, cloud shadows, rolling fog, aurora, starfield.
- Weather/terrain: rain, lightning, snow, ashfall, sand/dust, ocean shimmer.
- Magic/life: embers, fireflies, arcane motes, ley lines, drifting leaves, distant birds.
- Cartography: vignette, parchment warmth, moonlit tint, cartographer grid, compass rose.

Global **Intensity** and **Motion** sliders let you tune the whole combination without micromanaging every individual effect. Players with reduced-motion preferences automatically receive greatly reduced animation speed.

The player atlas also includes a type-filterable location panel, fixed-size markers that remain readable while zooming, marker focus behavior that keeps the selected location visible beside its lore drawer, and touch pinch zoom.

## Security notes

- The GM editor is password protected with `ADMIN_PASSWORD`.
- The player site is **invitation-only by default**. Revoked/rotated invitation sessions are revalidated on protected requests, including Codex, Atlas, Lore Network, images/uploads, search, and PDF preview.
- Railway deployments use Secure session cookies by default; local HTTP development automatically remains usable.
- Zip imports are extracted with path-traversal protection.
- File APIs cannot escape the campaign project root.
- LaTeX compilation disables shell escape by default and asks TeX to restrict file access. If your trusted campaign requires `minted` or another shell-escape feature, you can explicitly set `LATEX_ALLOW_SHELL_ESCAPE=1`.
- Do **not** enable shell escape on a deployment where untrusted people can edit LaTeX.

## Compatibility limits

The Docker image intentionally does not install `texlive-full`, because that image would be enormous. It includes the most common LaTeX, graphics, font, XeTeX and LuaTeX packages. If your current Overleaf source uses an uncommon system package, either:

- add the relevant Debian/TeX Live package to the `Dockerfile`; or
- include the custom `.sty` / `.cls` file in the project, as you normally can in Overleaf.

The wiki renderer is semantic rather than pixel-identical to the PDF. Your PDF preview is the exact place to verify TeX formatting; the player wiki intentionally reformats the same content into a responsive website.

## Tests

```bash
pip install pytest
pytest -q
```

## Why the campaign is not committed back to GitHub on every keystroke

Doing that would create a flood of commits and, with Railway GitHub auto-deploys enabled, could repeatedly redeploy the whole application while you type. Seeker therefore treats the persistent project volume as the authoring store and provides project ZIP export for backups/Overleaf interchange. GitHub remains the clean application/deployment repository.

## Fontspec / custom font projects

`fontspec` cannot compile under pdfLaTeX. Seeker now detects `fontspec`, `\setmainfont`, `\setsansfont`, `\setmonofont`, `unicode-math`, and `polyglossia` and automatically chooses XeLaTeX. Lua-only source is switched to LuaLaTeX. This works even if an older Railway deployment still has `LATEX_ENGINE=pdflatex`; `LATEX_ENGINE=auto` is nevertheless the recommended setting.

The Docker image includes OpenType **TeX Gyre** fonts and **EB Garamond**, so the commonly used:

```latex
\setmainfont{TeX Gyre Adventor}
```

works after rebuilding the Railway image. For a different private font, keep the `.otf`/`.ttf` in the LaTeX project and reference it through normal `fontspec` file/path options, or add the relevant Debian font package to the Dockerfile.

## Troubleshooting: `latexmk` says “Nothing to do” but also “pdflatex: gave an error”

That exact combination is usually a stale failed-build state in `latexmk`: its dependency database remembers a previous engine failure, then a later run decides there is nothing new to compile and only repeats the old failure summary.

Seeker detects this pattern automatically. It removes only generated LaTeX dependency/auxiliary state (`.fdb_latexmk`, `.fls`, `.aux`, `.toc`, etc.), retries with a forced dependency rebuild, and—if the wrapper still has no useful source diagnostic—runs the selected TeX engine directly once to recover the actual error message. The **Build log** shows a **Build Doctor** card describing any recovery step and likely fixes.

You can still press **↻ Clean** manually at any time. It does not delete your `.tex`, images, `.sty`, `.cls`, bibliography, maps, or Seeker metadata; it only clears generated compilation state before rebuilding.

If the underlying problem is real rather than stale state—for example a missing package, missing project `.sty`, undefined command, unmatched brace/environment, shell-escape requirement, or unavailable font—Build Doctor will keep the compile failed and show that cause instead of disguising it as the generic `latexmk` summary.

## Troubleshooting: `No space left on device` while importing

Seeker v1.0.1+ stages uploaded ZIP archives, extraction, and transactional rollback data in the service's ephemeral temporary filesystem rather than the persistent `/data` volume. This avoids requiring several copies of the same Overleaf project on the Railway volume during import.

If you previously attempted an import with an older Seeker build, open **Admin → Project → Railway persistence** and click **Clean failed-import leftovers**. The cleanup only targets legacy `project-backup-*`, `import-*`, and `upload-*.zip` artifacts; it does not delete the active `/data/project` campaign.

The Project screen also reports total, used, and free persistent storage. If the final uncompressed campaign itself does not fit, increase the Railway volume mounted at `/data` (paid Railway plans support live volume resizing) or reduce unused assets in the Overleaf source ZIP.


## v1.1 formatting and atlas fixes

This build adds regression coverage for longtable column-spec leakage, `\pon` entity grouping/profile rendering, TikZ NPC portrait extraction, persistent-volume migration for map atmosphere settings, and effect-setting validation. The test suite now includes regression coverage for Build Doctor recovery, automatic XeLaTeX selection for fontspec projects, PF2e semantic feat/action/item/monster rendering, scene art, deliberate TOC art, lore linking, batch Build Doctor repairs, and duplicate-geometry consolidation.

### Build Doctor engine sanity check (v1.3.5)

If the workspace says `Compilation failed · xelatex`, Build Doctor no longer infers a pdfLaTeX/fontspec problem merely because the words `fontspec` and `fatal` occur somewhere in the same long log. It reports that incompatibility only when TeX explicitly says fontspec was run under pdfTeX. Seeker also compares the selected engine with the engine banner actually seen in the log; a mismatch usually points to a project-local `latexmkrc`/`.latexmkrc` override.

### Large XeLaTeX books and `.xdv` output (v1.3.6)

When `latexmk -xelatex` runs, XeLaTeX deliberately typesets to an intermediate `.xdv` file and `latexmk` then calls `xdvipdfmx` to create the final PDF. Seeing a line such as `Output written on main.xdv (347 pages, ...)` therefore means the **TeX typesetting stage completed**; it is not itself an error.

Seeker now handles that pipeline explicitly. Large projects receive an adaptive build allowance, AUTO-selected XeLaTeX no longer clears auxiliary files on every compile, and a fresh `.xdv` can be converted to PDF in a separate recovery stage if the outer `latexmk` process stops before conversion. If `xdvipdfmx` fails, its own diagnostic is promoted to **FIRST BLOCKING ERROR**.

`LATEX_TIMEOUT` is now treated as the minimum per-stage allowance. Large XeLaTeX/LuaLaTeX projects may automatically receive 180–300 seconds so a long illustrated campaign book is not killed by the historical 60-second default.
