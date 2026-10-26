# Bundled map dependencies

These upstream distribution files are required by this module's backend asset
manifest and its local-first map loaders. Deploy this directory with the module;
missing CSS breaks backend style compilation before a CDN fallback can run.

| Library | Version | Source archive | License |
| --- | --- | --- | --- |
| Leaflet | 1.9.4 | https://registry.npmjs.org/leaflet/-/leaflet-1.9.4.tgz | BSD-2-Clause; see leaflet/LICENSE |
| Leaflet Routing Machine | 3.2.12 | https://registry.npmjs.org/leaflet-routing-machine/-/leaflet-routing-machine-3.2.12.tgz | ISC; see leaflet-routing-machine/LICENSE.md |

The selected JS/CSS distributions, referenced images and Leaflet source map are
copied without modification. Source archive SHA-256:

- Leaflet: `84c65a256e50657896f54c33bd857b6849ebe94c817803be818bf32a3dde0b77`
- Routing Machine: `5ca5d3a86a26c0fc213e3a1cc7b4270982edc3c0aa8cf9f226ae39e1aee7c0d7`

When updating dependencies, preserve licenses, update the versions in both map
widgets, include all CSS image dependencies and verify the compiled Odoo backend
bundle. The loader CDN fallback is not a substitute for files listed in assets.
