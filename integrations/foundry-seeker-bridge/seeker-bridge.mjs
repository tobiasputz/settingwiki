const MODULE_ID = "seeker-bridge";
const BRIDGE_VERSION = "1.2.1";
const BUNDLED_SEEKER_ORIGIN = "__SEEKER_PUBLIC_ORIGIN__";
let pushTimer = null;
let intervalId = null;
let bridgeStatus = "";
let lastBridgeNotice = 0;

function bridgeNotice(kind, message, {force = false} = {}) {
  const now = Date.now();
  const key = `${kind}:${message}`;
  if (!force && key === bridgeStatus && now - lastBridgeNotice < 120000) return;
  bridgeStatus = key;
  lastBridgeNotice = now;
  const notices = globalThis.ui?.notifications;
  const fn = notices?.[kind];
  if (typeof fn === "function") fn.call(notices, message);
}

function bundledSeekerOrigin() {
  const value = String(BUNDLED_SEEKER_ORIGIN || "").trim();
  if (!/^https?:\/\//i.test(value) || value.includes("__SEEKER_PUBLIC_ORIGIN__")) return "";
  try { return new URL(value).origin; } catch { return ""; }
}

function normalizedEndpoint(raw) {
  const value = String(raw || "").trim();
  if (!value) return "";
  try {
    const u = new URL(value);
    const local = ["localhost", "127.0.0.1", "0.0.0.0", "::1"].includes(u.hostname);
    if (u.protocol === "http:" && !local) u.protocol = "https:";

    // A Railway service can acquire a new/default hostname while the campaign token
    // and endpoint path remain valid. The public module ZIP is stamped with the origin
    // it was downloaded from, so an update can repair that stale hostname automatically.
    const bundled = bundledSeekerOrigin();
    if (!local && bundled && /^\/api\/v6\/foundry\/push\/\d+\/?$/.test(u.pathname)) {
      const canonical = new URL(bundled);
      u.protocol = canonical.protocol;
      u.host = canonical.host;
    }
    return u.href;
  } catch { return value; }
}

function setting(key) {
  return game.settings.get(MODULE_ID, key);
}
function i18n(key, fallback = "") {
  try {
    const out = String(game.i18n?.localize(key) || "");
    return out && out !== key ? out : (fallback || key);
  } catch { return fallback || key; }
}

function val(x, fallback = null) {
  if (x === null || x === undefined) return fallback;
  if (typeof x === "object" && "value" in x) return val(x.value, fallback);
  return x;
}
function num(x, fallback = null) {
  const n = Number(val(x, NaN));
  return Number.isFinite(n) ? n : fallback;
}
function arr(x) { return Array.isArray(x) ? x : []; }
function text(html, max = 2200) {
  const raw = String(html || "");
  if (!raw) return "";
  const div = document.createElement("div");
  div.innerHTML = raw;
  return String(div.textContent || div.innerText || "").replace(/\s+/g, " ").trim().slice(0, max);
}
function abs(url) {
  const raw = String(url || "").trim();
  if (!raw) return "";
  try { return new URL(raw, window.location.href).href; } catch { return raw; }
}
function rankLabel(rank) {
  const r = Number(rank);
  return ["Untrained", "Trained", "Expert", "Master", "Legendary"][Number.isFinite(r) ? r : 0] || "";
}
function stat(actor, slug) {
  try {
    const s = actor.getStatistic?.(slug);
    if (!s) return null;
    return {
      slug,
      label: i18n(s.label || slug, s.label || slug),
      mod: num(s.mod ?? s.check?.mod),
      dc: num(s.dc?.value ?? s.dc),
      rank: num(s.rank),
      rank_label: rankLabel(num(s.rank, 0)),
    };
  } catch { return null; }
}
function identityItem(actor, type) {
  const item = (actor.items?.contents || []).find(i => i.type === type);
  return item?.name || "";
}
function traitList(system) {
  const traits = val(system?.traits?.value, []);
  if (Array.isArray(traits)) return traits.map(String).slice(0, 30);
  if (traits && typeof traits === "object") return Object.keys(traits).slice(0, 30);
  return [];
}
function itemSummary(item) {
  const s = item.system || {};
  const equipped = s.equipped || {};
  return {
    id: item.id || "",
    uuid: item.uuid || "",
    name: item.name || "",
    type: item.type || "",
    img: abs(item.img),
    level: num(s.level),
    quantity: num(s.quantity, 1),
    bulk: String(val(s.bulk, val(s.weight, "")) ?? ""),
    equipped: Boolean(val(equipped.inSlot, false) || val(equipped.invested, false) || String(val(equipped.carryType, "")) === "worn"),
    carry_type: String(val(equipped.carryType, "") || ""),
    category: String(val(s.category, val(s.group, "")) || ""),
    traits: traitList(s),
    description: text(val(s.description, "")),
  };
}
function strikeSummary(actor) {
  const actions = arr(actor.system?.actions);
  return actions.filter(a => String(a?.type || "").toLowerCase() === "strike" || a?.item)
    .slice(0, 30).map(a => ({
      name: String(a?.label || a?.name || a?.item?.name || "Strike"),
      img: abs(a?.item?.img || ""),
      mod: num(a?.totalModifier ?? a?.modifier),
      damage: String(a?.damage?.formula || a?.damage?.damage || a?.damageFormula || ""),
      traits: arr(a?.traits).map(t => String(t?.label || t?.name || t)).slice(0, 16),
    }));
}
function actorOwners(actor) {
  const OWNER = globalThis.CONST?.DOCUMENT_OWNERSHIP_LEVELS?.OWNER ?? 3;
  const ownership = actor.ownership || {};
  return (game.users?.contents || []).filter(u => !u.isGM && Number(ownership[u.id] || 0) >= OWNER).map(u => u.name).slice(0, 20);
}
function actorUrl(actor) {
  const u = new URL(window.location.href);
  u.searchParams.set("seekerActor", actor.uuid || `Actor.${actor.id}`);
  u.hash = "";
  return u.href;
}
function actorSheet(actor) {
  const sys = actor.system || {};
  const attrs = sys.attributes || {};
  const resources = sys.resources || {};
  const abilityShort = { str: "STR", dex: "DEX", con: "CON", int: "INT", wis: "WIS", cha: "CHA" };
  const abilities = Object.entries(sys.abilities || {}).map(([slug, a]) => ({slug, label: abilityShort[String(slug || "").toLowerCase()] || i18n(String(a?.label || slug), String(a?.label || slug).toUpperCase()), mod: num(a?.mod)})).filter(a => a.mod !== null);
  const saveSlugs = ["fortitude", "reflex", "will"];
  const skillSlugs = ["acrobatics","arcana","athletics","crafting","deception","diplomacy","intimidation","medicine","nature","occultism","performance","religion","society","stealth","survival","thievery"];
  const saves = saveSlugs.map(x => stat(actor, x)).filter(Boolean);
  const skills = skillSlugs.map(x => stat(actor, x)).filter(Boolean);
  const perception = stat(actor, "perception");
  const allItems = (actor.items?.contents || []).slice(0, 300).map(itemSummary);
  const byTypes = (...types) => allItems.filter(i => types.includes(i.type));
  const classItem = identityItem(actor, "class");
  const ancestry = identityItem(actor, "ancestry");
  const heritage = identityItem(actor, "heritage");
  const background = identityItem(actor, "background");
  const hp = attrs.hp || {};
  const speedRaw = attrs.speed || {};
  const otherSpeeds = arr(speedRaw.otherSpeeds).map(s => ({type:String(s?.type||""), value:num(s?.value)})).filter(s => s.value !== null);
  const spellItems = byTypes("spell");
  const spellcasting = byTypes("spellcastingEntry");
  const spellsByRank = {};
  for (const spell of spellItems) {
    const rank = Number.isFinite(spell.level) ? spell.level : 0;
    (spellsByRank[String(rank)] ||= []).push(spell);
  }
  return {
    system: game.system?.id || "",
    identity: {
      level: num(sys.details?.level), class_name: classItem, ancestry, heritage, background,
      alignment: String(val(sys.details?.alignment, "") || ""),
      deity: String(val(sys.details?.deity?.value, val(sys.details?.deity, "")) || ""),
      languages: arr(val(sys.details?.languages?.value, [])).map(String),
      traits: traitList(sys),
    },
    vitals: {
      hp: {value:num(hp.value,0), max:num(hp.max,0), temp:num(hp.temp,0)},
      ac: num(attrs.ac), perception,
      speed: {value:num(speedRaw.value), other:otherSpeeds},
      hero_points: {value:num(resources.heroPoints?.value,0), max:num(resources.heroPoints?.max,3)},
      focus: {value:num(resources.focus?.value), max:num(resources.focus?.max)},
      dying: num(attrs.dying?.value), wounded:num(attrs.wounded?.value), doomed:num(attrs.doomed?.value),
      class_dc: num(attrs.classDC?.value ?? attrs.classDC),
    },
    abilities, saves, skills,
    strikes: strikeSummary(actor),
    conditions: byTypes("condition").map(i => ({name:i.name,img:i.img,description:i.description})),
    feats: byTypes("feat").map(i => ({...i, action_type: i.category})),
    actions: byTypes("action").map(i => ({...i})),
    inventory: byTypes("weapon","armor","shield","equipment","consumable","backpack","treasure","kit"),
    spells: spellsByRank,
    spellcasting,
    lore: byTypes("lore"),
    effects: byTypes("effect","affliction"),
    all_items_count: allItems.length,
  };
}
function actorSummary(actor) {
  return {
    id: actor.id,
    uuid: actor.uuid || `Actor.${actor.id}`,
    name: actor.name,
    img: abs(actor.img),
    url: actorUrl(actor),
    type: actor.type || "",
    active: true,
    owners: actorOwners(actor),
    sheet: actorSheet(actor),
  };
}
function sceneSummary(scene) {
  if (!scene) return {};
  return { id: scene.id, name: scene.name || "", img: abs(scene.background?.src || scene.img || "") };
}

function processedCommandIds() {
  try {
    const raw = JSON.parse(String(setting("processedCommands") || "[]"));
    return new Set(Array.isArray(raw) ? raw.map(x => String(x)) : []);
  } catch { return new Set(); }
}
async function rememberProcessedCommandId(id) {
  const out = Array.from(processedCommandIds());
  const value = String(id || "");
  if (!value || out.includes(value)) return;
  out.push(value);
  while (out.length > 250) out.shift();
  await game.settings.set(MODULE_ID, "processedCommands", JSON.stringify(out));
}
function ackEndpoint(rawEndpoint) {
  const u = new URL(normalizedEndpoint(rawEndpoint));
  u.pathname = `${u.pathname.replace(/\/+$/, "")}/ack`;
  return u.href;
}
function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}
function htmlDescription(summary, detail) {
  const parts = [String(summary || "").trim(), String(detail || "").trim()].filter(Boolean);
  return parts.map(chunk => `<p>${foundry.utils.escapeHTML(chunk).replace(/\n/g, "<br>")}</p>`).join("");
}
function slugList(input) {
  return String(input || "").split(",").map(x => x.trim()).filter(Boolean);
}
function numericOr(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}
function preparedAbilityHtml(data) {
  const abilities = Array.isArray(data?.abilities) ? data.abilities : [];
  return abilities.filter(a => a?.name || a?.description).map(a => {
    const actions = String(a?.actions || "");
    const glyph = actions === "reaction" ? "↺" : actions === "free" ? "◇" : actions === "1" ? "◆" : actions === "2" ? "◆◆" : actions === "3" ? "◆◆◆" : "";
    const traits = String(a?.traits || "").trim();
    return `<p><strong>${foundry.utils.escapeHTML(String(a?.name || "Ability"))}${glyph ? ` ${glyph}` : ""}</strong>${traits ? ` <em>(${foundry.utils.escapeHTML(traits)})</em>` : ""}<br>${foundry.utils.escapeHTML(String(a?.description || "")).replace(/\n/g,"<br>")}</p>`;
  }).join("");
}
function preparedAttackHtml(data) {
  const attacks = Array.isArray(data?.attacks) ? data.attacks : [];
  return attacks.filter(a => a?.name || a?.damage).map(a => {
    const type = String(a?.type || "melee") === "ranged" ? "Ranged" : "Melee";
    const bonus = Number(a?.bonus);
    const bonusText = Number.isFinite(bonus) ? `${bonus >= 0 ? "+" : ""}${bonus}` : "";
    const traits = String(a?.traits || "").trim();
    return `<p><strong>${type}</strong> ${foundry.utils.escapeHTML(String(a?.name || "Strike"))} ${bonusText}${traits ? ` (${foundry.utils.escapeHTML(traits)})` : ""}, <strong>Damage</strong> ${foundry.utils.escapeHTML(String(a?.damage || "—"))}</p>`;
  }).join("");
}
function preparedDetailsHtml(payload) {
  const data = payload?.data || {};
  const rows = [];
  const add = (label, value) => { const raw = String(value || "").trim(); if (raw) rows.push(`<p><strong>${label}</strong> ${foundry.utils.escapeHTML(raw)}</p>`); };
  add("Source", payload?.subtitle);
  add("Price", data.price); add("Bulk", data.bulk); add("Usage", data.usage);
  add("Prerequisites", data.prerequisites); add("Frequency", data.frequency || data.activation_frequency || data.homebrew_frequency);
  add("Trigger", data.trigger || data.activation_trigger || data.homebrew_trigger); add("Requirements", data.requirements || data.activation_requirements);
  add("Senses", data.senses); add("Languages", data.languages); add("Skills", data.skills);
  add("Immunities", data.immunities); add("Weaknesses", data.weaknesses); add("Resistances", data.resistances);
  if (data.spellcasting) rows.push(`<p><strong>Spellcasting</strong><br>${foundry.utils.escapeHTML(String(data.spellcasting)).replace(/\n/g,"<br>")}</p>`);
  return rows.join("") + preparedAttackHtml(data) + preparedAbilityHtml(data);
}
function buildPreparedItem(payload) {
  const data = payload?.data || {};
  const kind = String(payload?.prepared_kind || "item").toLowerCase();
  const type = kind === "feat" ? "feat" : kind === "homebrew" ? (String(data.homebrew_document || data.item_type || "equipment") || "equipment") : (String(data.item_type || "equipment") || "equipment");
  const description = htmlDescription(payload?.summary, data.description) + preparedDetailsHtml(payload);
  const system = {
    description: { value: description },
    level: { value: numericOr(data.level, 0) },
    quantity: Math.max(0, numericOr(data.quantity, 1)),
    traits: { value: slugList(data.traits), rarity: String(data.rarity || "common").toLowerCase() || "common" },
    slug: foundry.utils.slugify(String(payload?.title || "prepared-item")),
    source: { value: "Seeker" },
  };
  if (type === "feat" || type === "action") {
    const action = String(data.action_cost || data.homebrew_actions || "");
    system.actionType = { value: action === "reaction" ? "reaction" : action === "free" ? "free" : action ? "action" : "passive" };
    system.actions = { value: /^[123]$/.test(action) ? Number(action) : null };
    system.category = String(data.feat_category || "general");
    system.prerequisites = { value: String(data.prerequisites || "").trim() ? [{ value: String(data.prerequisites).trim() }] : [] };
  }
  return {
    name: String(payload?.title || "Prepared item"),
    type,
    img: String(data.img || "icons/svg/item-bag.svg"),
    system,
  };
}
function buildPreparedActor(payload) {
  const data = payload?.data || {};
  const hp = Math.max(1, numericOr(data.hp, 1));
  const speed = numericOr(data.speed, 25);
  const level = numericOr(data.level, 0);
  const publicNotes = htmlDescription(payload?.summary, data.description) + preparedDetailsHtml(payload);
  return {
    name: String(payload?.title || "Prepared creature"),
    type: "npc",
    img: String(data.img || "icons/svg/mystery-man.svg"),
    system: {
      details: {
        level: { value: level },
        alliance: String(data.actor_role || "npc") === "ally" ? "party" : "opposition",
        publicNotes,
        languages: { value: slugList(data.languages) },
      },
      traits: { value: slugList(data.traits), rarity: String(data.rarity || "common").toLowerCase() || "common", size: { value: String(data.size || "med") } },
      attributes: {
        ac: { value: Math.max(0, numericOr(data.ac, 10)) },
        hp: { value: hp, max: hp },
        speed: { value: speed },
        perception: { value: numericOr(data.perception, 0) },
      },
      perception: { mod: numericOr(data.perception, 0), details: String(data.senses || "") },
      saves: {
        fortitude: { value: numericOr(data.fortitude, 0) },
        reflex: { value: numericOr(data.reflex, 0) },
        will: { value: numericOr(data.will, 0) },
      },
      abilities: {
        str: { mod: numericOr(data.str_mod, 0) }, dex: { mod: numericOr(data.dex_mod, 0) },
        con: { mod: numericOr(data.con_mod, 0) }, int: { mod: numericOr(data.int_mod, 0) },
        wis: { mod: numericOr(data.wis_mod, 0) }, cha: { mod: numericOr(data.cha_mod, 0) },
      },
    },
  };
}
async function runFoundryCommand(command) {
  const type = String(command?.command_type || "").toLowerCase();
  const payload = command?.payload || {};
  const actorId = String(command?.actor_id || "");
  const actor = actorId ? game.actors?.get(actorId) : null;
  if (["adjust_resource", "adjust_item_quantity", "grant_prepared_content"].includes(type) && !actor) {
    throw new Error("Target actor is not available in this world.");
  }
  if (type === "adjust_resource") {
    const resource = String(payload.resource || "").toLowerCase();
    const delta = numericOr(payload.delta, 0);
    if (!delta) throw new Error("Delta cannot be zero.");
    let path = ""; let current = 0; let max = 999;
    if (resource === "hp") { path = "system.attributes.hp.value"; current = numericOr(actor.system?.attributes?.hp?.value, 0); max = Math.max(current, numericOr(actor.system?.attributes?.hp?.max, current)); }
    else if (resource === "temp_hp") { path = "system.attributes.hp.temp"; current = numericOr(actor.system?.attributes?.hp?.temp, 0); max = 999; }
    else if (resource === "hero_points") { path = "system.resources.heroPoints.value"; current = numericOr(actor.system?.resources?.heroPoints?.value, 0); max = Math.max(0, numericOr(actor.system?.resources?.heroPoints?.max, 3)); }
    else if (resource === "focus") { path = "system.resources.focus.value"; current = numericOr(actor.system?.resources?.focus?.value, 0); max = Math.max(0, numericOr(actor.system?.resources?.focus?.max, 3)); }
    else throw new Error("Unsupported resource.");
    const next = clamp(current + delta, 0, max);
    await actor.update({ [path]: next });
    return { message: `${actor.name}: ${resource.replace("_", " ")} ${delta > 0 ? "increased" : "decreased"} to ${next}.` };
  }
  if (type === "adjust_item_quantity") {
    const item = actor.items?.get(String(payload.item_id || ""));
    if (!item) throw new Error("Target item was not found on the actor.");
    const delta = numericOr(payload.delta, 0);
    if (!delta) throw new Error("Delta cannot be zero.");
    const current = Math.max(0, numericOr(item.system?.quantity, 1));
    const next = Math.max(0, current + delta);
    await item.update({ "system.quantity": next });
    return { message: `${item.name}: quantity updated to ${next}.` };
  }
  if (type === "grant_prepared_content") {
    const created = await actor.createEmbeddedDocuments("Item", [buildPreparedItem(payload)]);
    return { message: `${created?.[0]?.name || payload.title || "Prepared content"} added to ${actor.name}.` };
  }
  if (type === "push_prepared_content") {
    const kind = String(payload.prepared_kind || "item").toLowerCase();
    if (["npc", "monster"].includes(kind) || (kind === "homebrew" && (payload?.data?.hp || payload?.data?.ac))) {
      const created = await Actor.create(buildPreparedActor(payload));
      return { message: `${created?.name || payload.title || "Prepared creature"} created in the Actors directory.` };
    }
    const created = await Item.create(buildPreparedItem(payload));
    return { message: `${created?.name || payload.title || "Prepared content"} created in the Items directory.` };
  }
  throw new Error(`Unsupported command type: ${type}`);
}
async function acknowledgeCommands(endpoint, results) {
  if (!results?.length) return;
  const response = await fetch(ackEndpoint(endpoint), {
    method: "POST",
    mode: "cors",
    credentials: "omit",
    cache: "no-store",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ results })
  });
  if (!response.ok) throw new Error(`Seeker ack failed (${response.status}).`);
}
async function processCommands(endpoint, commands = []) {
  const queue = Array.isArray(commands) ? commands : [];
  if (!queue.length) return;
  const seen = processedCommandIds();
  const results = [];
  for (const command of queue) {
    const id = String(command?.id || "");
    if (!id) continue;
    if (seen.has(id)) {
      results.push({ id, status: "skipped", result: { message: "Command already processed on this Foundry world." } });
      continue;
    }
    try {
      const result = await runFoundryCommand(command);
      await rememberProcessedCommandId(id);
      results.push({ id, status: "done", result });
    } catch (error) {
      console.warn(`[${MODULE_ID}] Command ${id} failed`, error);
      results.push({ id, status: "failed", result: { message: error?.message || String(error) } });
    }
  }
  await acknowledgeCommands(endpoint, results);
  queuePush(200);
}

async function sendState() {
  if (!game.user?.isGM || !setting("enabled")) return;
  const configuredEndpoint = String(setting("endpoint") || "").trim();
  const endpoint = normalizedEndpoint(configuredEndpoint);
  if (!endpoint) {
    bridgeNotice("warn", "Seeker Bridge is enabled, but no bridge endpoint is configured.");
    return;
  }
  try {
    const combat = game.combat;
    const actorDocs = (game.actors?.contents || []).filter(a => a.hasPlayerOwner).slice(0, 60);
    const actors = [];
    for (const actor of actorDocs) {
      try { actors.push(actorSummary(actor)); }
      catch (error) {
        console.warn(`[${MODULE_ID}] Could not serialize actor ${actor?.name || actor?.id || "unknown"}`, error);
        actors.push({
          id: actor?.id || "", uuid: actor?.uuid || `Actor.${actor?.id || ""}`, name: actor?.name || "Character",
          img: abs(actor?.img || ""), url: actorUrl(actor), type: actor?.type || "character",
          active: true, owners: actorOwners(actor), sheet: {warning: "This actor could not be fully serialized by the bridge."}
        });
      }
    }
    const payload = {
      bridge_version: BRIDGE_VERSION,
      foundry_version: game.version || "",
      system: game.system?.id || "",
      system_version: game.system?.version || "",
      world: { id: game.world?.id || "", title: game.world?.title || "" },
      scene: sceneSummary(globalThis.canvas?.scene || game.scenes?.active),
      actors,
      combat: combat ? {
        active: !!combat.started,
        round: combat.round ?? null,
        turn: combat.turn ?? null,
        combatant: combat.combatant?.name || ""
      } : null,
      sent_at: Date.now()
    };
    const response = await fetch(endpoint, {
      method: "POST",
      mode: "cors",
      credentials: "omit",
      cache: "no-store",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload)
    });
    if (!response.ok) {
      let detail = "";
      try { detail = String((await response.json())?.detail || ""); } catch {}
      console.warn(`[${MODULE_ID}] Seeker rejected bridge state: ${response.status}`, detail);
      bridgeNotice("warn", `Seeker Bridge could not connect (${response.status})${detail ? `: ${detail}` : ". Check the campaign endpoint in Module Settings."}`);
      return;
    }
    let body = {};
    try { body = await response.json(); } catch {}
    await processCommands(endpoint, body?.commands || []);
    const firstSuccess = !String(bridgeStatus).startsWith("info:Seeker Bridge connected");
    bridgeStatus = "info:Seeker Bridge connected";
    if (firstSuccess) bridgeNotice("info", `Seeker Bridge connected · ${actors.length} player actor${actors.length === 1 ? "" : "s"} synced.`, {force: true});
  } catch (error) {
    console.warn(`[${MODULE_ID}] Could not reach Seeker`, error);
    const mixed = configuredEndpoint.startsWith("http://") && endpoint.startsWith("https://");
    const hint = mixed ? " The bridge automatically upgraded the public Seeker URL to HTTPS." : "";
    bridgeNotice("warn", `Seeker Bridge cannot reach Seeker.${hint} Open F12 → Console for the network error.`);
  }
}

function queuePush(delay = 900) {
  if (!game.user?.isGM) return;
  clearTimeout(pushTimer);
  pushTimer = setTimeout(sendState, delay);
}

Hooks.once("init", () => {
  game.settings.register(MODULE_ID, "enabled", {
    name: "Enable Seeker bridge",
    hint: "Only a GM client sends read-only campaign and player-character data to Seeker.",
    scope: "world", config: true, type: Boolean, default: false,
    onChange: () => queuePush(50)
  });
  game.settings.register(MODULE_ID, "endpoint", {
    name: "Seeker bridge endpoint",
    hint: "Paste the private endpoint shown under Seeker → GM → Integrations.",
    scope: "world", config: true, type: String, default: "",
    onChange: () => queuePush(50)
  });
  game.settings.register(MODULE_ID, "interval", {
    name: "Heartbeat interval (seconds)",
    hint: "Low-frequency refresh in case no Foundry hook fires. Minimum 30 seconds.",
    scope: "world", config: true, type: Number, default: 60,
    onChange: () => setupInterval()
  });
  game.settings.register(MODULE_ID, "processedCommands", {
    scope: "world", config: false, type: String, default: "[]"
  });
});

function setupInterval() {
  if (intervalId) clearInterval(intervalId);
  const seconds = Math.max(30, Number(setting("interval") || 60));
  intervalId = setInterval(() => {
    if (document.visibilityState === "visible") sendState();
  }, seconds * 1000);
}

async function openDeepLinkedActor() {
  if (!game.user) return;
  const u = new URL(window.location.href);
  const uuid = u.searchParams.get("seekerActor");
  if (!uuid) return;
  try {
    const actor = await fromUuid(uuid);
    if (actor?.sheet) actor.sheet.render(true);
  } catch (error) {
    console.warn(`[${MODULE_ID}] Could not open actor ${uuid}`, error);
  } finally {
    u.searchParams.delete("seekerActor");
    history.replaceState({}, "", u.pathname + (u.search ? u.search : "") + u.hash);
  }
}

Hooks.once("ready", () => {
  openDeepLinkedActor();
  if (!game.user?.isGM) return;
  setupInterval();
  queuePush(250);
  Hooks.on("canvasReady", () => queuePush());
  Hooks.on("updateScene", () => queuePush());
  Hooks.on("createActor", () => queuePush());
  Hooks.on("updateActor", () => queuePush(350));
  Hooks.on("deleteActor", () => queuePush());
  Hooks.on("createItem", item => item?.parent?.documentName === "Actor" && queuePush(350));
  Hooks.on("updateItem", item => item?.parent?.documentName === "Actor" && queuePush(350));
  Hooks.on("deleteItem", item => item?.parent?.documentName === "Actor" && queuePush(350));
  Hooks.on("createCombat", () => queuePush());
  Hooks.on("updateCombat", () => queuePush(350));
  Hooks.on("deleteCombat", () => queuePush());
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") queuePush(100);
  });
});
