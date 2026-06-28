# License Decision

The selected license for this basic public repo is Apache-2.0.

This file is not legal advice. It is a product/release checklist.

## Selected License

Apache-2.0 is included in [../LICENSE](../LICENSE).

Copyright notice:

```text
Copyright 2026 Anton Semenenko / SemeAI
```

Reason:

- permissive open-source distribution;
- explicit patent grant language;
- clearer enterprise comfort than a minimal permissive license;
- good fit for a public SDK/demo-style release-control adapter.

## Other Options Considered

### MIT

Simple and permissive.

Good if the goal is adoption, visibility, and easy reuse.

Tradeoff: competitors can reuse the code with few restrictions.

### Apache-2.0

Permissive, with explicit patent grant language.

Good if the goal is serious open-source distribution with clearer enterprise
comfort than MIT.

Tradeoff: slightly longer and more formal.

### Business Source License / delayed open source

Useful if the goal is public source visibility while restricting production
commercial use for a period.

Tradeoff: not accepted as standard open source by many communities.

## Release Rule

Do not publish a public package without keeping `LICENSE`, `pyproject.toml`,
and `sdks/node/package.json` aligned on Apache-2.0.
