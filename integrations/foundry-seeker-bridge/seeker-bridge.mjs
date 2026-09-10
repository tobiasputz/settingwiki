const MODULE_ID = "seeker-bridge";
const BRIDGE_VERSION = "1.1.0";
let pushTimer = null;
let intervalId = null;

function setting(key) {
  return game.settings.get(MODULE_ID, key);
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
      label: s.label || slug,
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
  const abilities = Object.entries(sys.abilities || {}).map(([slug, a]) => ({slug, label: String(a?.label || slug).toUpperCase(), mod: num(a?.mod)})).filter(a => a.mod !== null);
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

async function sendState() {
  if (!game.user?.isGM || !setting("enabled")) return;
  const endpoint = String(setting("endpoint") || "").trim();
  if (!endpoint) return;
  const combat = game.combat;
  const payload = {
    bridge_version: BRIDGE_VERSION,
    foundry_version: game.version || "",
    system: game.system?.id || "",
    system_version: game.system?.version || "",
    world: { id: game.world?.id || "", title: game.world?.title || "" },
    scene: sceneSummary(canvas?.scene || game.scenes?.active),
    actors: (game.actors?.contents || []).filter(a => a.hasPlayerOwner).slice(0, 60).map(actorSummary),
    combat: combat ? {
      active: !!combat.started,
      round: combat.round ?? null,
      turn: combat.turn ?? null,
      combatant: combat.combatant?.name || ""
    } : null,
    sent_at: Date.now()
  };
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      mode: "cors",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload)
    });
    if (!response.ok) console.warn(`[${MODULE_ID}] Seeker rejected bridge state: ${response.status}`);
  } catch (error) {
    console.warn(`[${MODULE_ID}] Could not reach Seeker`, error);
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
