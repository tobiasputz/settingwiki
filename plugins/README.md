# Seeker declarative extensions

Seeker extensions are intentionally **declarative**. A plugin can add navigation,
search entries, Campaign Object type labels, Forge presets, and actions that map to
existing Seeker Bridge commands without executing arbitrary Python inside Seeker.

Create `plugins/<plugin-id>/plugin.json`:

```json
{
  "id": "weather-tools",
  "title": "Weather Tools",
  "version": "1.0.0",
  "description": "Weather references for the campaign workspace.",
  "workspace_tab": {
    "label": "Weather",
    "href": "/plugins/weather-tools/index.html",
    "description": "Open the weather workspace"
  },
  "object_types": [
    {"id": "weather-front", "title": "Weather Front", "icon": "☁"}
  ],
  "search_entries": [
    {"id": "weather-guide", "kind": "reference", "title": "Weather Guide", "excerpt": "Campaign weather reference", "href": "/plugins/weather-tools/index.html"}
  ],
  "forge_types": [
    {
      "id": "weather-rule",
      "title": "Weather Rule",
      "icon": "☁",
      "description": "A reusable weather subsystem rule",
      "document": "equipment",
      "group": "Weather Rules",
      "preset": {"library_section": "other", "traits": "environmental"}
    }
  ],
  "foundry_actions": [
    {
      "id": "push-reference",
      "title": "Push reference",
      "command_type": "push_prepared_content",
      "scope": "world",
      "payload": {"prepared_kind": "item", "title": "Weather Reference"}
    }
  ]
}
```

## Extension points

- `workspace_tab` adds a Campaign Workspace navigation link.
- `search_entries` participates in universal GM search.
- `object_types` advertises specialized Campaign Object categories to extension-aware tools.
- `forge_types` adds a preset button to the Homebrew Forge. `preset` may populate any standard Forge field. Seeker stores `extension_plugin` and `extension_type` with the Homebrew entry so the origin is retained.
- `foundry_actions` adds buttons in Diagnostics > Extensions. For safety, an action may only use an existing Seeker Bridge command type (`push_prepared_content`, `push_ancestry_bundle`, `push_homebrew_rule_bundle`, `push_content_bundle`, `sync_entity_document`, `grant_prepared_content`, `adjust_resource`, or `adjust_item_quantity`).

A plugin may serve its own static/UI page using the normal Seeker deployment or a
reverse-proxied route. The manifest API intentionally does not import Python modules
from plugin folders; this keeps upgrades and third-party extensions from silently
executing server code.
