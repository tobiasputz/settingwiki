# Seeker Bridge for Foundry VTT

A deliberately read-only bridge. It sends lightweight table context from the active GM client to Seeker: current world/scene, player-owned actor names and portraits, and combat round/turn state. It does not create, edit, or delete Foundry documents.

## Install

1. Put the `seeker-bridge` folder in Foundry's `Data/modules/` directory, or install the ZIP downloaded from Seeker's Integrations page.
2. Enable **Seeker Bridge** for the world.
3. In **Configure Settings → Module Settings**, enable the bridge and paste the private endpoint from **Seeker → GM → Integrations**.
4. Reload the world once. Seeker's Integrations page should report the active scene shortly afterward.

Treat the endpoint like a password. Rotating the token in Seeker invalidates the old endpoint immediately.
