# Seeker Bridge for Foundry VTT

A read-only bridge from Foundry into Seeker. The GM client sends the active scene, combat context and a compact projection of player-owned actors. Seeker never creates, edits or deletes Foundry documents.

## Install through Foundry

1. In Seeker open **GM → Integrations** and copy the **Foundry manifest URL**.
2. In Foundry open **Add-on Modules → Install Module**.
3. Paste the URL into **Manifest URL** and click **Install**.
4. Enable **Seeker Bridge** in the world.
5. Open **Configure Settings → Module Settings**, enable the bridge and paste the private bridge endpoint shown in Seeker.
6. Reload the world once. Seeker should show the connected world and synced actors shortly afterward.

Seeker character dossiers can then be linked to a synced Foundry actor. Mechanical data remains read-only in Seeker; Foundry stays the source of truth.

Treat the private bridge endpoint like a password. Rotating the token in Seeker invalidates the old endpoint immediately.
