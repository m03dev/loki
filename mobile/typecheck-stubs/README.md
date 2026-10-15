Minimal type declarations for an OFFLINE typecheck (`npm run typecheck:offline`, which
needs only `tsc`), for machines where the npm registry is not reachable. They cover only
what this app uses, written from each package's documented API. They are not used by the
real build: after `npm install`, `npm run typecheck` checks against the real packages.
