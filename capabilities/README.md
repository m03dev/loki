# Capabilities

One folder per pluggable capability, each with a `manifest.json` (see
`engine/manifests.py` for the schema and permission vocabulary).

Loki **reads** these at startup and never imports or runs anything because of them. A
capability is off until you turn it on in **Settings > Capabilities**, which records the
permissions you granted. If a manifest changes later, it switches off again until you
re-approve it.

Your own manifests go in `harness_data/capabilities/<name>/manifest.json`. They are
treated as untrusted: they can never be enabled by default and cannot replace a built-in
manifest of the same name.
