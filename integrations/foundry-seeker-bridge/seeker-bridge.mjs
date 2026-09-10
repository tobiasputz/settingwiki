const MODULE_ID = "seeker-bridge";
let pushTimer = null;
let intervalId = null;

function setting(key) {
  return game.settings.get(MODULE_ID, key);
}

function actorSummary(actor) {
  return {
    id: actor.id,
    name: actor.name,
    img: actor.img || "",
    type: actor.type || "",
    active: true
  };
}

function sceneSummary(scene) {
  if (!scene) return {};
  return { id: scene.id, name: scene.name || "", img: scene.background?.src || scene.img || "" };
}

async function sendState() {
  if (!game.user?.isGM || !setting("enabled")) return;
  const endpoint = String(setting("endpoint") || "").trim();
  if (!endpoint) return;
  const combat = game.combat;
  const payload = {
    bridge_version: "1.0.0",
    world: { id: game.world?.id || "", title: game.world?.title || "" },
    scene: sceneSummary(canvas?.scene || game.scenes?.active),
    actors: (game.actors?.contents || []).filter(a => a.hasPlayerOwner).slice(0, 50).map(actorSummary),
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
    hint: "Only the active GM client sends read-only table context to Seeker.",
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

Hooks.once("ready", () => {
  if (!game.user?.isGM) return;
  setupInterval();
  queuePush(250);
  Hooks.on("canvasReady", () => queuePush());
  Hooks.on("updateScene", () => queuePush());
  Hooks.on("createActor", () => queuePush());
  Hooks.on("updateActor", () => queuePush());
  Hooks.on("deleteActor", () => queuePush());
  Hooks.on("createCombat", () => queuePush());
  Hooks.on("updateCombat", () => queuePush(350));
  Hooks.on("deleteCombat", () => queuePush());
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") queuePush(100);
  });
});
