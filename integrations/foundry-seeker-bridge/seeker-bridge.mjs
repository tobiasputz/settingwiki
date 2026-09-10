const MODULE_ID = "seeker-bridge";
const BRIDGE_VERSION = "1.5.0";
const BUNDLED_SEEKER_ORIGIN = "__SEEKER_PUBLIC_ORIGIN__";

function seekerSlugify(value) {
  const raw = String(value || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  return raw.replace(/[’']/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 128) || "seeker-entry";
}
function seekerEscapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch] || ch));
}
let pushTimer = null;
let intervalId = null;
let commandIntervalId = null;
let commandPollActive = false;
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
function commandsEndpoint(rawEndpoint) {
  const u = new URL(normalizedEndpoint(rawEndpoint));
  u.pathname = `${u.pathname.replace(/\/+$/, "")}/commands`;
  return u.href;
}
function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}
function htmlDescription(summary, detail) {
  const parts = [String(summary || "").trim(), String(detail || "").trim()].filter(Boolean);
  return parts.map(chunk => `<p>${seekerEscapeHTML(chunk).replace(/\n/g, "<br>")}</p>`).join("");
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
    return `<p><strong>${seekerEscapeHTML(String(a?.name || "Ability"))}${glyph ? ` ${glyph}` : ""}</strong>${traits ? ` <em>(${seekerEscapeHTML(traits)})</em>` : ""}<br>${seekerEscapeHTML(String(a?.description || "")).replace(/\n/g,"<br>")}</p>`;
  }).join("");
}
function preparedAttackHtml(data) {
  const attacks = Array.isArray(data?.attacks) ? data.attacks : [];
  return attacks.filter(a => a?.name || a?.damage).map(a => {
    const type = String(a?.type || "melee") === "ranged" ? "Ranged" : "Melee";
    const bonus = Number(a?.bonus);
    const bonusText = Number.isFinite(bonus) ? `${bonus >= 0 ? "+" : ""}${bonus}` : "";
    const traits = String(a?.traits || "").trim();
    return `<p><strong>${type}</strong> ${seekerEscapeHTML(String(a?.name || "Strike"))} ${bonusText}${traits ? ` (${seekerEscapeHTML(traits)})` : ""}, <strong>Damage</strong> ${seekerEscapeHTML(String(a?.damage || "—"))}</p>`;
  }).join("");
}
function preparedDetailsHtml(payload) {
  const data = payload?.data || {};
  const rows = [];
  const add = (label, value) => { const raw = String(value || "").trim(); if (raw) rows.push(`<p><strong>${label}</strong> ${seekerEscapeHTML(raw)}</p>`); };
  add("Source", payload?.subtitle);
  add("Price", data.price); add("Bulk", data.bulk); add("Usage", data.usage);
  add("Prerequisites", data.prerequisites); add("Frequency", data.frequency || data.activation_frequency || data.homebrew_frequency);
  add("Trigger", data.trigger || data.activation_trigger || data.homebrew_trigger); add("Requirements", data.requirements || data.activation_requirements);
  add("Senses", data.senses); add("Languages", data.languages); add("Skills", data.skills);
  add("Immunities", data.immunities); add("Weaknesses", data.weaknesses); add("Resistances", data.resistances);
  if (data.spellcasting) rows.push(`<p><strong>Spellcasting</strong><br>${seekerEscapeHTML(String(data.spellcasting)).replace(/\n/g,"<br>")}</p>`);
  return rows.join("") + preparedAttackHtml(data) + preparedAbilityHtml(data);
}
function absoluteSeekerAsset(raw, endpoint = "") {
  const value = String(raw || "").trim();
  if (!value) return "";
  if (/^(?:https?:|data:|icons\/|systems\/|modules\/)/i.test(value)) return value;
  try { return new URL(value, normalizedEndpoint(endpoint)).href; } catch { return value; }
}
function parsedCoins(raw) {
  const out = {};
  const text = String(raw || "").toLowerCase();
  for (const match of text.matchAll(/(\d+(?:\.\d+)?)\s*(pp|gp|sp|cp)\b/g)) {
    const amount = Number(match[1]);
    if (Number.isFinite(amount) && amount >= 0) out[match[2]] = (out[match[2]] || 0) + amount;
  }
  return out;
}
function parsedBulk(raw) {
  const value = String(raw || "").trim().toUpperCase();
  if (!value || value === "-" || value === "—") return 0;
  if (value === "L") return 1;
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? Math.round(number * 10) : 0;
}
function validWeaponRange(raw) {
  const value = Math.trunc(numericOr(raw, 0));
  const allowed = new Set([10,15,20,30,40,50,60,70,80,90,100,110,120,140,150,180,200,240,300]);
  return allowed.has(value) ? value : null;
}
function buildPreparedItem(payload, endpoint = "") {
  const data = payload?.data || {};
  const kind = String(payload?.prepared_kind || "item").toLowerCase();
  const type = kind === "feat" ? "feat" : kind === "homebrew" ? (String(data.homebrew_document || data.item_type || "equipment") || "equipment") : (String(data.item_type || "equipment") || "equipment");
  const description = htmlDescription(payload?.summary, data.description) + preparedDetailsHtml(payload);
  const traitChoices = type === "weapon" ? globalThis.CONFIG?.PF2E?.weaponTraits
    : type === "feat" ? globalThis.CONFIG?.PF2E?.featTraits
    : type === "action" ? globalThis.CONFIG?.PF2E?.actionTraits
    : globalThis.CONFIG?.PF2E?.equipmentTraits;
  const system = {
    description: { value: description },
    level: { value: numericOr(data.level, 0) },
    quantity: Math.max(0, numericOr(data.quantity, 1)),
    traits: { value: validTraitList(data.traits, traitChoices), rarity: String(data.rarity || "common").toLowerCase() || "common" },
    slug: seekerSlugify(String(payload?.title || "prepared-item")),
    source: { value: "Seeker" },
  };
  const physicalTypes = new Set(["weapon","armor","shield","equipment","consumable","backpack","treasure","kit"]);
  if (physicalTypes.has(type)) {
    const hands = Math.max(0, Math.min(2, Math.trunc(numericOr(data.hands, 0))));
    system.price = { value: parsedCoins(data.price), per: 1 };
    system.bulk = { value: parsedBulk(data.bulk) };
    system.hp = { value: 0, max: 0 };
    system.hardness = 0;
    system.equipped = { carryType: "worn", handsHeld: hands, invested: null };
    system.identification = { status: "identified", unidentified: null };
    system.containerId = null;
    system.material = { type: null, grade: null };
    system.size = "med";
  }
  if (type === "weapon") {
    const dice = Math.max(0, Math.min(8, Math.trunc(numericOr(data.weapon_damage_dice, 1))));
    const die = ["d4","d6","d8","d10","d12"].includes(String(data.weapon_damage_die || "").toLowerCase()) ? String(data.weapon_damage_die).toLowerCase() : "d6";
    const damageType = validChoice(data.weapon_damage_type, globalThis.CONFIG?.PF2E?.damageTypes, "slashing");
    const group = choiceSlug(data.weapon_group, globalThis.CONFIG?.PF2E?.weaponGroups) || null;
    const category = validChoice(data.weapon_category, globalThis.CONFIG?.PF2E?.weaponCategories, "simple");
    const allowedUsage = new Set(["worngloves","held-in-one-hand","held-in-one-plus-hands","held-in-two-hands"]);
    const usage = allowedUsage.has(String(data.weapon_usage || "")) ? String(data.weapon_usage) : (String(data.hands) === "2" ? "held-in-two-hands" : "held-in-one-hand");
    const baseSlug = String(data.weapon_base || "").trim() ? seekerSlugify(data.weapon_base) : "";
    const baseChoices = globalThis.CONFIG?.PF2E?.baseWeaponTypes;
    const baseItem = baseSlug && baseChoices && Object.prototype.hasOwnProperty.call(baseChoices, baseSlug) ? baseSlug : null;
    const range = validWeaponRange(data.weapon_range);
    const reloadCandidate = String(data.weapon_reload || "").trim();
    const reloadRaw = new Set(["-","0","1","2","3","10"]).has(reloadCandidate) ? reloadCandidate : "";
    system.category = category;
    system.group = group;
    system.baseItem = baseItem;
    system.bonus = { value: Math.trunc(numericOr(data.weapon_bonus, 0)) };
    system.damage = {
      dice,
      die: dice > 0 ? die : null,
      damageType,
      modifier: Math.trunc(numericOr(data.weapon_damage_modifier, 0)),
      persistent: null,
    };
    system.splashDamage = { value: 0 };
    system.range = range;
    system.reload = { value: reloadRaw || null };
    system.usage = { value: usage };
    system.runes = {
      potency: Math.max(0, Math.min(4, Math.trunc(numericOr(data.weapon_potency, 0)))),
      striking: Math.max(0, Math.min(4, Math.trunc(numericOr(data.weapon_striking, 0)))),
      property: [],
    };
  }
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
    img: absoluteSeekerAsset(data.img, endpoint) || "icons/svg/item-bag.svg",
    flags: { seeker: { managed: true, entityId: payload?.entity_id ?? null, preparedId: payload?.prepared_id ?? payload?.prepared_content_id ?? null } },
    system,
  };
}
function tokenGridSize(size) {
  const slug = String(size || "med").toLowerCase();
  return ({ tiny: 1, sm: 1, med: 1, lg: 2, huge: 3, grg: 4 })[slug] || 1;
}
function choiceSlug(raw, choices) {
  const value = String(raw || "").trim();
  if (!value) return "";
  const direct = seekerSlugify(value);
  if (!choices || typeof choices !== "object") return direct;
  if (Object.prototype.hasOwnProperty.call(choices, direct)) return direct;
  const lowered = value.toLowerCase();
  for (const [key, label] of Object.entries(choices)) {
    const localized = i18n(String(label || ""), String(label || ""));
    if (String(key).toLowerCase() === lowered || localized.toLowerCase() === lowered) return key;
  }
  return "";
}
function parsedLanguages(raw) {
  const known = [];
  const unknown = [];
  for (const label of slugList(raw)) {
    const slug = choiceSlug(label, globalThis.CONFIG?.PF2E?.languages);
    if (slug) known.push(slug); else unknown.push(label);
  }
  return { value: [...new Set(known)], details: unknown.join(", ") };
}
function parsedNpcSkills(raw) {
  const result = {};
  const rows = String(raw || "").split(/[;,\n]+/).map(x => x.trim()).filter(Boolean);
  for (const row of rows) {
    const match = row.match(/^(.+?)\s*([+-]\s*\d+)(?:\s*\((.+)\))?$/);
    if (!match) continue;
    const slug = seekerSlugify(match[1]);
    const base = Number(match[2].replace(/\s+/g, ""));
    if (!slug || !Number.isFinite(base)) continue;
    result[slug] = { base, note: String(match[3] || "") };
  }
  return result;
}
function parsedSenses(raw) {
  const senses = [];
  for (const chunk of String(raw || "").split(/[,;]+/).map(x => x.trim()).filter(Boolean)) {
    const normalized = chunk.toLowerCase();
    if (normalized === "darkvision") { senses.push({ type: "darkvision" }); continue; }
    if (["low-light vision", "low light vision", "low-light-vision"].includes(normalized)) { senses.push({ type: "low-light-vision" }); continue; }
    const range = Number(normalized.match(/(\d+)\s*(?:feet|foot|ft)?/)?.[1] || 0);
    const acuity = normalized.includes("vague") ? "vague" : normalized.includes("precise") && !normalized.includes("imprecise") ? "precise" : "imprecise";
    const typeRaw = normalized.replace(/\([^)]*\)/g, "").replace(/\d+\s*(?:feet|foot|ft)?/g, "").replace(/\b(?:precise|imprecise|vague)\b/g, "").trim();
    const type = choiceSlug(typeRaw, globalThis.CONFIG?.PF2E?.senseTypes);
    if (type && range >= 5) senses.push({ type, acuity, range });
  }
  return senses;
}
function parsedIWR(raw, kind) {
  const choices = kind === "immunity" ? globalThis.CONFIG?.PF2E?.immunityTypes : kind === "weakness" ? globalThis.CONFIG?.PF2E?.weaknessTypes : globalThis.CONFIG?.PF2E?.resistanceTypes;
  const result = [];
  for (const chunk of String(raw || "").split(/[,;]+/).map(x => x.trim()).filter(Boolean)) {
    const match = chunk.match(/^(.+?)(?:\s+(\d+))?(?:\s*\(.+\))?$/);
    if (!match) continue;
    const type = choiceSlug(match[1], choices);
    if (!type) continue;
    if (kind === "immunity") result.push({ type });
    else {
      const value = Number(match[2] || 0);
      if (value > 0) result.push({ type, value });
    }
  }
  return result;
}
function buildPreparedActor(payload, endpoint = "") {
  const data = payload?.data || {};
  const hp = Math.max(1, numericOr(data.hp, 1));
  const speed = numericOr(data.speed, 25);
  const level = numericOr(data.level, 0);
  const publicNotes = htmlDescription(payload?.summary, data.description) + preparedDetailsHtml(payload);
  const portrait = absoluteSeekerAsset(data.img, endpoint) || "icons/svg/mystery-man.svg";
  const token = absoluteSeekerAsset(data.token_img || data.img, endpoint) || portrait;
  const gridSize = tokenGridSize(data.size);
  return {
    name: String(payload?.title || "Prepared creature"),
    type: "npc",
    img: portrait,
    flags: { seeker: { managed: true, entityId: payload?.entity_id ?? null, preparedId: payload?.prepared_id ?? payload?.prepared_content_id ?? null } },
    prototypeToken: {
      name: String(payload?.title || "Prepared creature"),
      width: gridSize,
      height: gridSize,
      disposition: String(data.actor_role || "npc") === "ally" ? 1 : -1,
      texture: { src: token, scaleX: 1, scaleY: 1 },
    },
    system: {
      details: {
        level: { value: level },
        alliance: String(data.actor_role || "npc") === "ally" ? "party" : "opposition",
        blurb: String(payload?.summary || ""),
        publicNotes,
        privateNotes: String(data.gm_notes || ""),
        languages: parsedLanguages(data.languages),
      },
      traits: { value: validTraitList(data.traits, globalThis.CONFIG?.PF2E?.creatureTraits), rarity: String(data.rarity || "common").toLowerCase() || "common", size: { value: String(data.size || "med") } },
      attributes: {
        ac: { value: Math.max(0, numericOr(data.ac, 10)), details: "" },
        hp: { value: hp, max: hp, temp: 0, details: "" },
        speed: { value: speed, otherSpeeds: [], details: "" },
        immunities: parsedIWR(data.immunities, "immunity"),
        weaknesses: parsedIWR(data.weaknesses, "weakness"),
        resistances: parsedIWR(data.resistances, "resistance"),
        adjustment: null,
        allSaves: { value: "" },
      },
      perception: { mod: numericOr(data.perception, 0), details: String(data.senses || ""), senses: parsedSenses(data.senses), vision: true },
      skills: parsedNpcSkills(data.skills),
      initiative: { statistic: "perception" },
      saves: {
        fortitude: { value: numericOr(data.fortitude, 0), saveDetail: "" },
        reflex: { value: numericOr(data.reflex, 0), saveDetail: "" },
        will: { value: numericOr(data.will, 0), saveDetail: "" },
      },
      abilities: {
        str: { mod: numericOr(data.str_mod, 0) }, dex: { mod: numericOr(data.dex_mod, 0) },
        con: { mod: numericOr(data.con_mod, 0) }, int: { mod: numericOr(data.int_mod, 0) },
        wis: { mod: numericOr(data.wis_mod, 0) }, cha: { mod: numericOr(data.cha_mod, 0) },
      },
    },
  };
}
function validChoice(value, choices, fallback = "") {
  const v = String(value || "").trim().toLowerCase();
  if (!v) return fallback;
  if (!choices || typeof choices !== "object") return v;
  return Object.prototype.hasOwnProperty.call(choices, v) ? v : fallback;
}
function validTraitList(input, choices) {
  return slugList(input)
    .map(t => seekerSlugify(String(t || "")))
    .filter(Boolean)
    .filter(t => !choices || typeof choices !== "object" || Object.prototype.hasOwnProperty.call(choices, t));
}
function parseDamage(attack) {
  let formula = String(attack?.damage || "").trim();
  let type = String(attack?.damage_type || "").trim().toLowerCase();
  const known = globalThis.CONFIG?.PF2E?.damageTypes || {};
  if (!type && formula) {
    const last = formula.match(/\s+([a-z-]+)$/i)?.[1]?.toLowerCase();
    if (last && Object.prototype.hasOwnProperty.call(known, last)) {
      type = last;
      formula = formula.replace(new RegExp(`\\s+${last}$`, "i"), "").trim();
    }
  }
  if (!type || !Object.prototype.hasOwnProperty.call(known, type)) type = "bludgeoning";
  return { formula: formula || "1d4", type };
}
function buildNpcAttack(attack = {}) {
  const { formula, type } = parseDamage(attack);
  const ranged = String(attack.type || "melee").toLowerCase() === "ranged";
  const range = ranged ? Math.max(5, Math.round(numericOr(attack.range, 30) / 5) * 5) : 0;
  return {
    name: String(attack.name || "Strike"),
    type: "melee",
    img: ranged ? "icons/svg/target.svg" : "icons/svg/sword.svg",
    flags: { seeker: { managedEmbedded: true, role: "strike" } },
    system: {
      description: { value: "" },
      traits: {
        value: validTraitList(attack.traits, globalThis.CONFIG?.PF2E?.npcAttackTraits),
        otherTags: [],
      },
      rules: [],
      slug: seekerSlugify(String(attack.name || "strike")),
      action: "strike",
      area: null,
      bonus: { value: Math.trunc(numericOr(attack.bonus, 0)) },
      // PF2e 8.x stores NPC strike damage in a RecordField named damageRolls.
      // Use a stable non-empty key and the exact MeleeSystemSource field names.
      damageRolls: { "seeker-base": { damage: formula, damageType: type, category: type === "bleed" ? "persistent" : null } },
      attackEffects: { value: slugList(attack.effects).map(String) },
      range: ranged ? { increment: range, max: null } : null,
      subjectToMAP: true,
    },
  };
}
function npcAttackPatch(attack = {}) {
  const { formula, type } = parseDamage(attack);
  const ranged = String(attack.type || "melee").toLowerCase() === "ranged";
  const range = ranged ? Math.max(5, Math.round(numericOr(attack.range, 30) / 5) * 5) : 0;
  return {
    "system.bonus.value": Math.trunc(numericOr(attack.bonus, 0)),
    "system.damageRolls": { "seeker-base": { damage: formula, damageType: type, category: type === "bleed" ? "persistent" : null } },
    "system.range": ranged ? { increment: range, max: null } : null,
  };
}
function abilityActionData(ability = {}) {
  const raw = String(ability.actions || "").toLowerCase();
  if (raw === "reaction") return { type: "reaction", actions: null };
  if (raw === "free") return { type: "free", actions: null };
  if (/^[123]$/.test(raw)) return { type: "action", actions: Number(raw) };
  return { type: "passive", actions: null };
}
function abilityFrequency(ability = {}) {
  const per = String(ability.frequency_per || "").trim();
  if (!per) return null;
  const allowed = new Set(["turn", "round", "PT1M", "PT10M", "PT1H", "PT24H", "day", "P1W", "P1M", "P1Y"]);
  if (!allowed.has(per)) return null;
  const max = Math.max(1, Math.trunc(numericOr(ability.frequency_max, 1)));
  return { value: max, max, per };
}
function abilityInlineCheck(ability = {}) {
  const type = String(ability.dc_type || "").trim().toLowerCase();
  const dc = Math.trunc(numericOr(ability.dc, 0));
  if (!type || dc <= 0) return "";
  const params = [type, `dc:${dc}`];
  if (["fortitude", "reflex", "will"].includes(type) && Boolean(ability.dc_basic)) params.push("basic");
  const show = String(ability.dc_show || "owner").trim().toLowerCase();
  if (["gm", "all", "none"].includes(show)) params.push(`showDC:${show}`);
  return `@Check[${params.join("|")}]`;
}
function abilityInlineDamage(ability = {}) {
  const formula = String(ability.damage || "").trim();
  if (!formula) return "";
  const type = validChoice(ability.damage_type, globalThis.CONFIG?.PF2E?.damageTypes, "untyped");
  return type && type !== "untyped" ? `@Damage[(${formula})[${type}]]` : `@Damage[${formula}]`;
}
function buildAbilityDescription(ability = {}) {
  const chunks = [];
  const trigger = String(ability.trigger || "").trim();
  const requirements = String(ability.requirements || "").trim();
  if (trigger) chunks.push(`<p><strong>Trigger</strong> ${seekerEscapeHTML(trigger)}</p>`);
  if (requirements) chunks.push(`<p><strong>Requirements</strong> ${seekerEscapeHTML(requirements)}</p>`);
  const check = abilityInlineCheck(ability);
  const damage = abilityInlineDamage(ability);
  const lead = [check, damage].filter(Boolean).join("; ");
  if (lead) chunks.push(`<p>${lead}</p>`);
  const description = String(ability.description || "").trim();
  if (description) chunks.push(htmlDescription("", description));
  return chunks.join("");
}
function buildNpcAbility(ability = {}) {
  const action = abilityActionData(ability);
  const category = ["offensive", "defensive", "interaction"].includes(String(ability.category || "").toLowerCase())
    ? String(ability.category).toLowerCase() : null;
  return {
    name: String(ability.name || "Special Ability"),
    type: "action",
    img: "icons/svg/aura.svg",
    flags: { seeker: { managedEmbedded: true, role: "ability" } },
    system: {
      description: { value: buildAbilityDescription(ability) },
      traits: {
        value: validTraitList(ability.traits, globalThis.CONFIG?.PF2E?.actionTraits),
        otherTags: [],
      },
      rules: [],
      slug: seekerSlugify(String(ability.name || "special-ability")),
      actionType: { value: action.type },
      actions: { value: action.actions },
      category,
      frequency: abilityFrequency(ability),
    },
  };
}
function emptySpellSlots(spells = [], mode = "innate") {
  const slots = {};
  for (let rank = 0; rank <= 10; rank += 1) {
    const rows = spells.filter(s => Math.max(0, Math.min(10, Math.trunc(numericOr(s?.rank, 1)))) === rank);
    const count = mode === "innate" || mode === "focus" ? 0 : rows.length;
    slots[`slot${rank}`] = { prepared: [], value: count, max: count };
  }
  return slots;
}
function buildSpellcastingEntry(data = {}) {
  const tradition = ["arcane", "divine", "occult", "primal"].includes(String(data.spell_tradition || "").toLowerCase())
    ? String(data.spell_tradition).toLowerCase() : "arcane";
  const mode = ["innate", "spontaneous", "prepared", "focus"].includes(String(data.spell_mode || "").toLowerCase())
    ? String(data.spell_mode).toLowerCase() : "innate";
  const dc = Math.max(0, Math.trunc(numericOr(data.spell_dc, 10)));
  const attackRaw = String(data.spell_attack ?? "").trim();
  // PF2e's own bestiary data convention uses DC - 8 when only a DC is known.
  const attack = attackRaw === "" ? Math.max(0, dc - 8) : Math.trunc(numericOr(data.spell_attack, 0));
  return {
    name: `${tradition.charAt(0).toUpperCase()}${tradition.slice(1)} ${mode.charAt(0).toUpperCase()}${mode.slice(1)} Spells`,
    type: "spellcastingEntry",
    img: "icons/svg/book.svg",
    flags: { seeker: { managedEmbedded: true, role: "spellcasting" } },
    system: {
      description: { value: htmlDescription("", data.spellcasting), gm: "" },
      traits: { otherTags: [] },
      rules: [],
      slug: null,
      ability: { value: "cha" },
      spelldc: { value: attack, dc },
      tradition: { value: tradition },
      prepared: { value: mode, flexible: false, validItems: null },
      showSlotlessLevels: { value: true },
      proficiency: { slug: "", value: 0 },
      slots: emptySpellSlots(Array.isArray(data.spells) ? data.spells : [], mode),
      autoHeightenLevel: { value: null },
    },
  };
}
function spellcastingPatch(data = {}) {
  const dc = Math.max(0, Math.trunc(numericOr(data.spell_dc, 10)));
  const attackRaw = String(data.spell_attack ?? "").trim();
  const attack = attackRaw === "" ? Math.max(0, dc - 8) : Math.trunc(numericOr(data.spell_attack, 0));
  const tradition = ["arcane", "divine", "occult", "primal"].includes(String(data.spell_tradition || "").toLowerCase()) ? String(data.spell_tradition).toLowerCase() : "arcane";
  const mode = ["innate", "spontaneous", "prepared", "focus"].includes(String(data.spell_mode || "").toLowerCase()) ? String(data.spell_mode).toLowerCase() : "innate";
  return {
    "system.spelldc.value": attack,
    "system.spelldc.dc": dc,
    "system.tradition.value": tradition,
    "system.prepared.value": mode,
    "system.showSlotlessLevels.value": true,
  };
}
function spellTime(raw) {
  const value = String(raw || "2").trim().toLowerCase();
  if (value === "reaction") return "reaction";
  if (value === "free") return "free action";
  if (/^[123]$/.test(value)) return `${value} action${value === "1" ? "" : "s"}`;
  return value || "2 actions";
}
function spellDefense(raw, basic = false) {
  const value = String(raw || "").trim().toLowerCase();
  if (value === "ac") return { passive: { statistic: "ac" }, save: null };
  if (["fortitude", "reflex", "will"].includes(value)) return { passive: null, save: { statistic: value, basic: Boolean(basic) } };
  return null;
}
function buildHomebrewSpell(spell = {}, entryId = "", data = {}) {
  const rankRaw = Math.max(0, Math.min(10, Math.trunc(numericOr(spell.rank, 1))));
  const cantrip = rankRaw === 0;
  const rank = Math.max(1, rankRaw);
  const tradition = ["arcane", "divine", "occult", "primal"].includes(String(data.spell_tradition || "").toLowerCase())
    ? String(data.spell_tradition).toLowerCase() : "arcane";
  const traits = validTraitList(spell.traits, globalThis.CONFIG?.PF2E?.spellTraits);
  if (cantrip && !traits.includes("cantrip")) traits.push("cantrip");
  const damageFormula = String(spell.damage || "").trim();
  const damageType = validChoice(spell.damage_type, globalThis.CONFIG?.PF2E?.damageTypes, "force");
  const mode = String(data.spell_mode || "innate").toLowerCase();
  const uses = mode === "innate" ? { value: 1, max: 1 } : undefined;
  return {
    name: String(spell.name || "Homebrew Spell"),
    type: "spell",
    img: "icons/svg/book.svg",
    flags: { seeker: { managedEmbedded: true, role: "spell" } },
    system: {
      description: { value: htmlDescription("", spell.description) },
      traits: { value: traits, rarity: "common", traditions: [tradition] },
      rules: [],
      slug: seekerSlugify(String(spell.name || "homebrew-spell")),
      level: { value: rank },
      requirements: "",
      target: { value: String(spell.target || "") },
      range: { value: String(spell.range || "") },
      area: null,
      time: { value: spellTime(spell.actions) },
      duration: { value: String(spell.duration || ""), sustained: false },
      damage: damageFormula ? { "0": { formula: damageFormula, kinds: ["damage"], type: damageType, category: null, materials: [] } } : {},
      defense: spellDefense(spell.save, spell.basic),
      cost: { value: "" },
      counteraction: false,
      ritual: null,
      location: { value: entryId || null, signature: false, heightenedLevel: cantrip ? rank : undefined, uses },
    },
  };
}
async function findCompendiumSpell(name, sourceUuid = "") {
  const exactUuid = String(sourceUuid || "").trim();
  if (exactUuid && /^(?:Compendium\.|Item\.)/i.test(exactUuid)) {
    try {
      const exact = await fromUuid(exactUuid);
      if (exact?.type === "spell") return exact;
    } catch (error) {
      console.debug(`[${MODULE_ID}] Could not resolve exact spell UUID ${exactUuid}`, error);
    }
  }
  const needle = String(name || "").trim().toLowerCase();
  if (!needle) return null;
  const preferred = game.packs?.get?.("pf2e.spells-srd");
  const allItemPacks = (game.packs?.contents || []).filter(p => p.documentName === "Item");
  const packs = [preferred, ...allItemPacks.filter(p => p !== preferred)].filter(Boolean);
  const slugNeedle = seekerSlugify(needle);
  for (const pack of packs) {
    try {
      const index = await pack.getIndex({ fields: ["type", "system.slug"] });
      const hit = index.find(e => String(e.type || "").toLowerCase() === "spell" && (
        String(e.name || "").trim().toLowerCase() === needle || seekerSlugify(e.system?.slug || e.name || "") === slugNeedle
      ));
      if (!hit) continue;
      const doc = await pack.getDocument(hit._id);
      if (doc?.type === "spell") return doc;
    } catch (error) {
      console.debug(`[${MODULE_ID}] Could not search spell pack ${pack.collection}`, error);
    }
  }
  return null;
}
async function buildPreparedSpell(spell, entryId, data) {
  const official = await findCompendiumSpell(spell?.name, spell?.source_uuid);
  if (!official) return buildHomebrewSpell(spell, entryId, data);
  const source = official.toObject();
  delete source._id;
  source.flags = { ...(source.flags || {}), seeker: { managedEmbedded: true, role: "spell" } };
  source.system ||= {};
  source.system.location = {
    ...(source.system.location || {}),
    value: entryId,
    signature: false,
    uses: String(data?.spell_mode || "").toLowerCase() === "innate" ? { value: 1, max: 1 } : source.system.location?.uses,
  };
  const enteredRank = Math.max(0, Math.min(10, Math.trunc(numericOr(spell?.rank, 0))));
  if (enteredRank > 0 && source.system.level) source.system.location.heightenedLevel = Math.max(Number(source.system.level.value || 1), enteredRank);
  return source;
}
async function addSpellToEntry(actor, entry, spell, data) {
  const enteredRank = Math.max(0, Math.min(10, Math.trunc(numericOr(spell?.rank, 0))));
  const groupId = enteredRank === 0 ? "cantrips" : enteredRank;
  const official = await findCompendiumSpell(spell?.name, spell?.source_uuid);
  if (official && entry?.spells?.addSpell) {
    try {
      const created = await entry.spells.addSpell(official, { groupId });
      if (created) {
        const mode = String(data?.spell_mode || "innate").toLowerCase();
        const uses = Math.max(1, Math.trunc(numericOr(spell?.uses, 1)));
        const updates = {};
        if (mode === "innate") updates["system.location.uses"] = { value: uses, max: uses };
        if (enteredRank > 0 && created.baseRank && enteredRank >= Number(created.baseRank)) updates["system.location.heightenedLevel"] = enteredRank;
        updates["flags.seeker.managedEmbedded"] = true;
        updates["flags.seeker.role"] = "spell";
        await created.update(updates);
        return created;
      }
    } catch (error) {
      console.debug(`[${MODULE_ID}] SpellCollection.addSpell failed for ${spell?.name}; falling back to direct embed`, error);
    }
  }
  const source = official ? official.toObject() : buildHomebrewSpell(spell, entry.id, data);
  if (official) {
    delete source._id;
    source.flags = { ...(source.flags || {}), seeker: { managedEmbedded: true, role: "spell" } };
    source.system ||= {};
    source.system.location = { ...(source.system.location || {}), value: entry.id, signature: false };
    if (enteredRank > 0) source.system.location.heightenedLevel = enteredRank;
    if (String(data?.spell_mode || "").toLowerCase() === "innate") {
      const uses = Math.max(1, Math.trunc(numericOr(spell?.uses, 1)));
      source.system.location.uses = { value: uses, max: uses };
    }
  }
  const docs = await actor.createEmbeddedDocuments("Item", [source]);
  return docs?.[0] || null;
}
async function populatePreparedActor(actor, payload) {
  const data = payload?.data || {};
  const report = { attacks: 0, abilities: 0, spells: 0, spellcasting: 0, warnings: [] };
  const attacks = (Array.isArray(data.attacks) ? data.attacks : []).filter(a => String(a?.name || a?.damage || "").trim());
  if (attacks.length) {
    for (const attack of attacks) {
      try {
        const created = (await actor.createEmbeddedDocuments("Item", [buildNpcAttack(attack)]))?.[0];
        if (!created) throw new Error("Strike document was not created.");
        // Re-apply numeric/damage data after creation. This avoids migrations/defaults
        // in different PF2e releases eating the custom values from the create source.
        await created.update(npcAttackPatch(attack));
        const { formula, type } = parseDamage(attack);
        const storedDamage = Object.values(created.system?.damageRolls || {}).find(d => String(d?.damage || "").trim() === formula);
        if (!storedDamage) {
          // Some PF2e releases migrate a newly-created melee item before the first
          // update finishes. A second, source-shaped replacement is harmless and
          // makes the intended damage roll deterministic across those releases.
          await created.update({ "system.damageRolls": { "seeker-base": { damage: formula, damageType: type, category: type === "bleed" ? "persistent" : null } } });
        }
        if (!Object.values(created.system?.damageRolls || {}).length) throw new Error("PF2e did not retain the strike damage roll.");
        report.attacks += 1;
      } catch (error) {
        console.warn(`[${MODULE_ID}] Could not create prepared NPC attack ${attack?.name || "Strike"}`, error);
        report.warnings.push(`attack ${attack?.name || "Strike"}: ${error?.message || error}`);
      }
    }
  }
  const abilities = (Array.isArray(data.abilities) ? data.abilities : []).filter(a => String(a?.name || a?.description || "").trim());
  if (abilities.length) {
    try {
      const created = await actor.createEmbeddedDocuments("Item", abilities.map(buildNpcAbility));
      report.abilities = created.length;
    } catch (error) {
      console.warn(`[${MODULE_ID}] Could not create prepared NPC abilities`, error);
      report.warnings.push(`abilities: ${error?.message || error}`);
    }
  }
  const spells = (Array.isArray(data.spells) ? data.spells : []).filter(s => String(s?.name || "").trim());
  if (spells.length) {
    try {
      const entries = await actor.createEmbeddedDocuments("Item", [buildSpellcastingEntry(data)]);
      const entry = entries?.[0];
      if (!entry) throw new Error("Spellcasting entry was not created.");
      await entry.update(spellcastingPatch(data));
      const wantedDC = Math.max(0, Math.trunc(numericOr(data.spell_dc, 10)));
      const attackRaw = String(data.spell_attack ?? "").trim();
      const wantedAttack = attackRaw === "" ? Math.max(0, wantedDC - 8) : Math.trunc(numericOr(data.spell_attack, 0));
      // Verify the source values PF2e actually retained. These are the two
      // explicit NPC spell statistic inputs used by PF2e when it prepares the
      // spell attack and spell DC statistics.
      if (Number(entry.system?.spelldc?.dc) !== wantedDC || Number(entry.system?.spelldc?.value) !== wantedAttack) {
        await entry.update({ "system.spelldc": { value: wantedAttack, dc: wantedDC } });
      }
      report.spellcasting = 1;
      const created = [];
      for (const spell of spells) {
        try {
          const doc = await addSpellToEntry(actor, entry, spell, data);
          if (doc) { created.push(doc); report.spells += 1; }
          else report.warnings.push(`spell ${spell?.name || "unknown"}: Foundry did not add the spell.`);
        } catch (error) {
          console.warn(`[${MODULE_ID}] Could not add spell ${spell?.name || "unknown"}`, error);
          report.warnings.push(`spell ${spell?.name || "unknown"}: ${error?.message || error}`);
        }
      }
      if (String(data.spell_mode || "").toLowerCase() === "prepared") {
        const slotPatch = {};
        for (let rank = 1; rank <= 10; rank += 1) {
          const rankSpells = created.filter(doc => Math.max(0, Math.trunc(numericOr(doc?.rank ?? doc?.system?.level?.value, 1))) === rank);
          if (!rankSpells.length) continue;
          slotPatch[`system.slots.slot${rank}.max`] = rankSpells.length;
          slotPatch[`system.slots.slot${rank}.value`] = rankSpells.length;
          slotPatch[`system.slots.slot${rank}.prepared`] = rankSpells.map(s => ({ id: s.id, expended: false }));
        }
        if (Object.keys(slotPatch).length) await entry.update(slotPatch);
      }
    } catch (error) {
      console.warn(`[${MODULE_ID}] Could not create prepared NPC spellcasting`, error);
      report.warnings.push(`spellcasting: ${error?.message || error}`);
    }
  }
  return report;
}

function compactManagedItem(item) {
  const source = item?.toObject?.(false) || {};
  const sys = source.system || {};
  return {
    id: item?.id || source._id || "",
    uuid: item?.uuid || "",
    name: item?.name || source.name || "",
    type: item?.type || source.type || "",
    img: item?.img || source.img || "",
    role: item?.flags?.seeker?.role || "",
    system: {
      description: sys.description || {}, level: sys.level || {}, traits: sys.traits || {},
      actionType: sys.actionType || {}, actions: sys.actions || {}, frequency: sys.frequency ?? null,
      bonus: sys.bonus || {}, damageRolls: sys.damageRolls || {}, range: sys.range ?? null,
      spelldc: sys.spelldc || {}, tradition: sys.tradition || {}, prepared: sys.prepared || {},
      location: sys.location || {}, damage: sys.damage || {}, defense: sys.defense || {}, time: sys.time || {},
    },
  };
}

function managedDocumentSummary(doc) {
  const seeker = doc?.flags?.seeker || {};
  if (!seeker.managed || !seeker.entityId) return null;
  const source = doc?.toObject?.(false) || {};
  const sys = source.system || {};
  const snapshot = {
    name: doc.name || source.name || "",
    type: doc.type || source.type || "",
    img: doc.img || source.img || "",
  };
  if (doc.documentName === "Actor") {
    snapshot.prototypeToken = source.prototypeToken ? {
      width: source.prototypeToken.width, height: source.prototypeToken.height,
      disposition: source.prototypeToken.disposition, texture: source.prototypeToken.texture || {},
    } : null;
    snapshot.system = {
      details: sys.details || {}, traits: sys.traits || {}, attributes: sys.attributes || {}, perception: sys.perception || {},
      skills: sys.skills || {}, initiative: sys.initiative || {}, saves: sys.saves || {}, abilities: sys.abilities || {},
    };
    snapshot.items = (doc.items?.contents || []).filter(i => i?.flags?.seeker?.managedEmbedded).map(compactManagedItem).slice(0, 120);
  } else {
    snapshot.system = sys;
  }
  return {
    uuid: doc.uuid || "",
    document_type: doc.documentName || "",
    seeker: { entity_id: seeker.entityId, prepared_id: seeker.preparedId ?? null },
    snapshot,
  };
}

function managedDocuments() {
  const docs = [ ...(game.actors?.contents || []), ...(game.items?.contents || []) ];
  return docs.map(managedDocumentSummary).filter(Boolean).slice(0, 250);
}

async function syncManagedDocument(doc, payload, endpoint = "") {
  if (!doc) throw new Error("The linked Foundry document no longer exists.");
  const flag = doc?.flags?.seeker || {};
  const expected = String(payload?.entity_id ?? "");
  if (!flag.managed || !expected || String(flag.entityId ?? "") !== expected) {
    throw new Error("Seeker refused to update a Foundry document it does not own.");
  }
  const kind = String(payload?.prepared_kind || "item").toLowerCase();
  if (doc.documentName === "Actor" || ["npc","monster"].includes(kind)) {
    if (doc.documentName !== "Actor") throw new Error("The linked document is not an Actor.");
    const source = buildPreparedActor(payload, endpoint);
    await doc.update({ name: source.name, img: source.img, prototypeToken: source.prototypeToken, system: source.system });
    const managedIds = (doc.items?.contents || []).filter(i => i?.flags?.seeker?.managedEmbedded).map(i => i.id).filter(Boolean);
    if (managedIds.length) await doc.deleteEmbeddedDocuments("Item", managedIds);
    const report = await populatePreparedActor(doc, payload);
    return { message: `${doc.name} synchronized from Seeker.`, report, uuid: doc.uuid, document_type: "Actor", entity_id: payload.entity_id };
  }
  if (doc.documentName !== "Item") throw new Error("The linked document is not an Item.");
  const source = buildPreparedItem(payload, endpoint);
  if (String(doc.type) !== String(source.type)) throw new Error("Changing a linked Foundry item's document type is intentionally blocked; create a new item instead.");
  await doc.update({ name: source.name, img: source.img, system: source.system });
  return { message: `${doc.name} synchronized from Seeker.`, uuid: doc.uuid, document_type: "Item", entity_id: payload.entity_id };
}

async function runFoundryCommand(command, endpoint = "") {
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
    const created = await actor.createEmbeddedDocuments("Item", [buildPreparedItem(payload, endpoint)]);
    return { message: `${created?.[0]?.name || payload.title || "Prepared content"} added to ${actor.name}.`, uuid: created?.[0]?.uuid || "", document_type: "Item", entity_id: payload.entity_id ?? null };
  }
  if (type === "push_prepared_content") {
    const kind = String(payload.prepared_kind || "item").toLowerCase();
    if (["npc", "monster"].includes(kind) || (kind === "homebrew" && (payload?.data?.hp || payload?.data?.ac))) {
      const created = await Actor.create(buildPreparedActor(payload, endpoint));
      const report = await populatePreparedActor(created, payload);
      const extras = [
        report.attacks ? `${report.attacks} strike${report.attacks === 1 ? "" : "s"}` : "",
        report.abilities ? `${report.abilities} abilit${report.abilities === 1 ? "y" : "ies"}` : "",
        report.spells ? `${report.spells} spell${report.spells === 1 ? "" : "s"}` : "",
      ].filter(Boolean).join(", ");
      const warning = report.warnings.length ? ` Some embedded data could not be created: ${report.warnings.join("; ")}` : "";
      return { message: `${created?.name || payload.title || "Prepared creature"} created in the Actors directory${extras ? ` with ${extras}` : ""}.${warning}`, report, uuid: created?.uuid || "", document_type: "Actor", entity_id: payload.entity_id ?? null };
    }
    const created = await Item.create(buildPreparedItem(payload, endpoint));
    return { message: `${created?.name || payload.title || "Prepared content"} created in the Items directory.`, uuid: created?.uuid || "", document_type: "Item", entity_id: payload.entity_id ?? null };
  }
  if (type === "sync_entity_document") {
    const uuid = String(payload.foundry_uuid || "").trim();
    if (!uuid) throw new Error("No Foundry UUID is linked to this entity.");
    const doc = await fromUuid(uuid);
    return syncManagedDocument(doc, payload, endpoint);
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
      const result = await runFoundryCommand(command, endpoint);
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

async function pollCommands() {
  if (commandPollActive || !game.user?.isGM || !setting("enabled") || document.visibilityState !== "visible") return;
  const endpoint = normalizedEndpoint(String(setting("endpoint") || "").trim());
  if (!endpoint) return;
  commandPollActive = true;
  try {
    const response = await fetch(commandsEndpoint(endpoint), {
      method: "POST", mode: "cors", credentials: "omit", cache: "no-store",
      headers: {"Content-Type": "application/json"}
    });
    if (!response.ok) return;
    const body = await response.json().catch(() => ({}));
    await processCommands(endpoint, body?.commands || []);
  } catch (error) {
    console.debug(`[${MODULE_ID}] Lightweight command poll failed`, error);
  } finally {
    commandPollActive = false;
  }
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
      managed_documents: managedDocuments(),
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

function setupCommandInterval() {
  if (commandIntervalId) clearInterval(commandIntervalId);
  // Keep mechanical snapshots inexpensive, but make Seeker → Foundry actions feel
  // immediate. This endpoint carries no actor sheet payload unless work exists.
  commandIntervalId = setInterval(pollCommands, 3000);
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
  setupCommandInterval();
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
    if (document.visibilityState === "visible") { pollCommands(); queuePush(100); }
  });
});
