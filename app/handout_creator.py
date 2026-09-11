"""Handout presets and safe, portable document rendering. No external services."""
from html import escape
import json
from bs4 import BeautifulSoup
from fastapi import HTTPException
from .storage import connect

PRESETS = [{'id': 'letter', 'category': 'Correspondence', 'name': 'Personal letter', 'heading': 'Dear friend,', 'body': 'I write with news from beyond the northern pass.', 'signature': 'Yours faithfully'}, {'id': 'royal_decree', 'category': 'Authority', 'name': 'Royal decree', 'heading': 'By order of the Crown', 'body': 'Let it be known throughout the realm…', 'signature': 'Under the royal seal'}, {'id': 'wanted', 'category': 'Notices', 'name': 'Wanted poster', 'heading': 'WANTED', 'body': 'Last seen near the old gate. Approach with caution.', 'signature': 'Report to the watch'}, {'id': 'bounty', 'category': 'Notices', 'name': 'Bounty contract', 'heading': 'A reward awaits', 'body': 'Bring proof that the threat has been dealt with.', 'signature': 'Payment upon verification'}, {'id': 'quest', 'category': 'Adventures', 'name': 'Quest brief', 'heading': 'A call for capable hands', 'body': 'Objective: investigate the ruined observatory.\n\nComplication: its light has returned.', 'signature': 'Speak to the patron'}, {'id': 'rumors', 'category': 'Adventures', 'name': 'Rumor sheet', 'heading': 'Whispers around town', 'body': 'The ferryman refuses passage after dusk.\nThe bells ring from an empty tower.', 'signature': 'Heard at the tavern'}, {'id': 'journal', 'category': 'Correspondence', 'name': 'Journal page', 'heading': 'From a weathered journal', 'body': 'Day 17. The footprints end at the water, but something followed us home.', 'signature': 'The remaining pages are missing'}, {'id': 'diary', 'category': 'Correspondence', 'name': 'Secret diary', 'heading': 'For my eyes alone', 'body': 'I saw the same stranger again tonight.', 'signature': 'Do not trust the smiling mask'}, {'id': 'invitation', 'category': 'Correspondence', 'name': 'Formal invitation', 'heading': 'You are cordially invited', 'body': 'Join us for a feast beneath the harvest moon.', 'signature': 'Kindly present this invitation'}, {'id': 'threat', 'category': 'Correspondence', 'name': 'Threatening message', 'heading': 'One final warning', 'body': 'Leave the relic where you found it.', 'signature': 'We are watching'}, {'id': 'newspaper', 'category': 'Notices', 'name': 'Town newspaper', 'heading': 'The daily herald', 'body': 'MYSTERIOUS LIGHTS ABOVE THE MARSH\n\nWitnesses disagree about what they saw.', 'signature': 'News from every corner'}, {'id': 'notice', 'category': 'Notices', 'name': 'Public notice', 'heading': 'Notice to all residents', 'body': 'The eastern bridge is closed until further notice.', 'signature': 'Office of the steward'}, {'id': 'menu', 'category': 'Commerce', 'name': 'Tavern menu', 'heading': 'Food, drink & lodging', 'body': 'Hunter’s stew — 4 copper\nSpiced cider — 2 copper\nA room for the night — 1 silver', 'signature': 'No credit after midnight'}, {'id': 'shop', 'category': 'Commerce', 'name': 'Merchant catalogue', 'heading': 'Fine goods for discerning travelers', 'body': 'Lantern — 5 silver\nSilken rope — 2 gold\nSealed mystery box — ask within', 'signature': 'All sales final'}, {'id': 'receipt', 'category': 'Commerce', 'name': 'Receipt', 'heading': 'Proof of purchase', 'body': 'Received: three healing draughts\nPaid: 12 gold', 'signature': 'Keep this for your records'}, {'id': 'ledger', 'category': 'Commerce', 'name': 'Merchant ledger', 'heading': 'Accounts & obligations', 'body': 'First moon: delivery received.\nSecond moon: payment overdue.', 'signature': 'Balance carried forward'}, {'id': 'contract', 'category': 'Authority', 'name': 'Binding contract', 'heading': 'An agreement between parties', 'body': 'The undersigned agree to the following terms…', 'signature': 'Signed and witnessed'}, {'id': 'permit', 'category': 'Authority', 'name': 'Travel permit', 'heading': 'Safe conduct', 'body': 'The bearer is permitted passage through the northern gates.', 'signature': 'Valid until the next full moon'}, {'id': 'certificate', 'category': 'Authority', 'name': 'Certificate & title', 'heading': 'Let all bear witness', 'body': 'In recognition of distinguished service to the realm.', 'signature': 'Recorded in the royal register'}, {'id': 'testament', 'category': 'Authority', 'name': 'Last will', 'heading': 'My final wishes', 'body': 'To those who survive me, I entrust the following…', 'signature': 'Witnessed in sound mind'}, {'id': 'prophecy', 'category': 'Lore & magic', 'name': 'Prophecy', 'heading': 'When the third star falls', 'body': 'The child of ash shall open the door that has no key.', 'signature': 'Translated from the old tongue'}, {'id': 'spell', 'category': 'Lore & magic', 'name': 'Spell scroll', 'heading': 'Words of power', 'body': 'Trace the sign in silver dust and speak the forgotten name.', 'signature': 'Handle with care'}, {'id': 'ritual', 'category': 'Lore & magic', 'name': 'Ritual instructions', 'heading': 'The rite of returning', 'body': 'Prepare the circle.\nLight the three candles.\nSpeak only when the shadows answer.', 'signature': 'Never break the circle'}, {'id': 'prayer', 'category': 'Lore & magic', 'name': 'Prayer & hymn', 'heading': 'A blessing for the road', 'body': 'Keep our lanterns burning through the long night.', 'signature': 'So may it be'}, {'id': 'inscription', 'category': 'Lore & magic', 'name': 'Ancient inscription', 'heading': 'Carved into the stone', 'body': 'WE KEPT THE GATE\nWE PAID THE PRICE\nDO NOT WAKE WHAT SLEEPS', 'signature': 'A fragment of a lost age'}, {'id': 'recipe', 'category': 'Lore & magic', 'name': 'Alchemical recipe', 'heading': 'A curious preparation', 'body': 'Moonwater — one vial\nAsh of elderwood — a pinch\nStir until the mixture turns silver.', 'signature': 'Do not inhale the vapors'}, {'id': 'clue', 'category': 'Adventures', 'name': 'Evidence card', 'heading': 'Recovered evidence', 'body': 'Found beneath the floorboards of the abandoned inn.', 'signature': 'Filed for investigation'}, {'id': 'riddle', 'category': 'Adventures', 'name': 'Riddle & puzzle', 'heading': 'An inscription on the door', 'body': 'I speak without a mouth and follow without feet. What am I?', 'signature': 'An answer is required'}, {'id': 'map', 'category': 'Adventures', 'name': 'Map & directions', 'heading': 'The hidden route', 'body': 'Follow the river until the split oak.\nTurn east where the ravens gather.', 'signature': 'X marks the destination'}, {'id': 'relic', 'category': 'Adventures', 'name': 'Relic card', 'heading': 'An object of uncertain origin', 'body': 'Cold to the touch, even beside an open flame.', 'signature': 'Its purpose remains unknown'}, {'id': 'faction', 'category': 'Authority', 'name': 'Faction dossier', 'heading': 'A matter of allegiance', 'body': 'Known agents, territories, symbols, and recent activity.', 'signature': 'Prepared for the council'}, {'id': 'blank', 'category': 'Custom', 'name': 'Blank document', 'heading': '', 'body': '', 'signature': ''}]
PRESET_THEMES = {
    "letter":"parchment","journal":"weathered","diary":"weathered","invitation":"ivory","threat":"crimson",
    "royal_decree":"ivory","contract":"ivory","permit":"ink","certificate":"ivory","testament":"parchment","faction":"ink",
    "wanted":"weathered","bounty":"weathered","newspaper":"ink","notice":"ink",
    "menu":"parchment","shop":"ivory","receipt":"ink","ledger":"weathered",
    "quest":"parchment","rumors":"weathered","clue":"ink","riddle":"parchment","map":"weathered","relic":"midnight",
    "prophecy":"midnight","spell":"midnight","ritual":"midnight","prayer":"ivory","inscription":"weathered","recipe":"weathered",
    "blank":"parchment",
}
PRESET_SYMBOLS = {
    "letter":"✉","royal_decree":"♛","wanted":"⚠","bounty":"◎","quest":"⚔","rumors":"☞","journal":"✎","diary":"⌁",
    "invitation":"❦","threat":"☠","newspaper":"▤","notice":"!","menu":"♨","shop":"◇","receipt":"#","ledger":"≡",
    "contract":"§","permit":"⌘","certificate":"✦","testament":"†","prophecy":"☾","spell":"✧","ritual":"◉","prayer":"☼",
    "inscription":"ᚱ","recipe":"⚗","clue":"⌕","riddle":"?","map":"⌖","relic":"◆","faction":"⚜","blank":"□",
}
PRESET_VISUALS = {
    "newspaper":"masthead + columns","wanted":"bold notice border","royal_decree":"formal seal","journal":"handwritten notes",
    "menu":"tavern bill","spell":"arcane scroll","prophecy":"oracle fragment","map":"route sketch","receipt":"merchant slip",
    "invitation":"ornate card","threat":"crimson warning","faction":"dossier file",
}
for _preset in PRESETS:
    _preset["theme"] = PRESET_THEMES.get(_preset["id"], "parchment")
    _preset["symbol"] = PRESET_SYMBOLS.get(_preset["id"], "✦")
    _preset["visual"] = PRESET_VISUALS.get(_preset["id"], _preset["category"].lower())

THEMES = {"parchment", "ivory", "midnight", "weathered", "ink", "crimson"}

def clean_html(value):
    soup=BeautifulSoup(str(value or ""), "html.parser")
    for node in soup(["script","style","iframe","object","svg","math","form","input","button"]): node.decompose()
    for node in soup.find_all(True):
        if node.name not in {"p","br","strong","b","em","i","u","h2","h3","ul","ol","li","blockquote","hr","table","thead","tbody","tr","th","td"}: node.unwrap()
        else: node.attrs={}
    return str(soup)

def normalize(data):
    if not isinstance(data,dict): raise HTTPException(400,"Document must be an object")
    out={}
    for key,limit in {"preset":60,"theme":30,"heading":300,"subtitle":500,"body":100000,"signature":1000,"seal":60,"gm_notes":30000,"folder":120}.items():
        value=data.get(key, "")
        if not isinstance(value,str) or len(value)>limit: raise HTTPException(400,f"Invalid {key} (maximum {limit} characters)")
        out[key]=value
    if out["preset"] not in {p["id"] for p in PRESETS}: raise HTTPException(400,"Unknown preset")
    if out["theme"] not in THEMES: raise HTTPException(400,"Unknown paper style")
    return out

def render_body(d):
    def para(value):
        return "".join("<p>"+escape(x).replace("\n","<br>")+"</p>" for x in value.split("\n\n") if x.strip())
    return '<div class="hc-subtitle">'+escape(d['subtitle'])+'</div><h2>'+escape(d['heading'])+'</h2>'+para(d['body'])+'<div class="hc-signature">'+para(d['signature'])+'</div><div class="hc-seal">'+escape(d['seal'])+'</div>'

def metadata(settings, hid):
    with connect(settings) as conn:
        row=conn.execute("SELECT data FROM handout_designs WHERE handout_id=?",(hid,)).fetchone()
    return json.loads(row['data']) if row else None

def save_metadata(settings,hid,data):
    with connect(settings) as conn: conn.execute("INSERT INTO handout_designs(handout_id,data) VALUES(?,?) ON CONFLICT(handout_id) DO UPDATE SET data=excluded.data",(hid,json.dumps(data)))
