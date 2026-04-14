# Home Assistant Addon Workflow

How HA addon changes are developed, tested, and released.

## Repositories

| Repo | Branch | Purpose |
|------|--------|---------|
| `Suncuss/BirdNET-PiPy` (public) | `ha` | HA-specific frontend/backend builds; squash-synced from `dev` |
| `Suncuss/hassio-addon-birdnet-pipy` | `main` | Our addon repo — Dockerfile, s6 services, ingress config |
| `alexbelgium/hassio-addons` | `master` | Alex's addon repo — what HA users actually install |

The `ha` branch on BirdNET-PiPy is the source code the addon Dockerfile pulls. The addon repo wraps it with HA-specific infrastructure (s6 services, ingress nginx, config.yaml).

## Architecture Differences

The standard deployment uses Docker Compose with separate containers (api, model-server, icecast, nginx). The HA addon runs everything in a single container using s6-overlay:

- `cont-init.d/` scripts run as root at startup (structure, config, nginx patching)
- `services.d/` scripts run as root, drop privileges via `gosu` where needed
- Nginx serves both direct access (port 80) and HA ingress (sidebar iframe)
- Ingress mode injects `<base href>` and uses `sub_filter` to rewrite paths in served content

Key differences that cause HA-specific bugs:
- Single container means shared filesystem permissions (e.g., root-created dirs + non-root services)
- Ingress proxy adds a path prefix (`/api/hassio_ingress/TOKEN/`) to all requests
- `sub_filter` does byte-level text replacement — can match unintended strings in JS bundles

## Development Cycle

### 1. Develop and test on `dev`

Work on the `dev` branch of BirdNET-PiPy as usual. For HA-specific frontend fixes (e.g., relative paths for ingress), commit here first — these changes must be safe for non-HA users too.

### 2. Sync `dev` to `ha`

```bash
git checkout ha
git read-tree --reset -u dev
git commit -m "chore: sync ha with dev"
git push origin ha
git push public ha
git checkout dev
```

### 3. Test with our addon repo

The addon Dockerfile in `Suncuss/hassio-addon-birdnet-pipy` pulls from the `ha` branch:

```dockerfile
ARG BIRDNET_PIPY_VERSION=ha
```

To test addon-side changes (s6 services, ingress config, Dockerfile):

1. Edit files in `hassio-addon-birdnet-pipy/birdnet-pipy/`
2. Bump version in `config.yaml` (use `X.Y.Z-devN` format, e.g., `0.6.2-dev0`)
3. Commit and push to `main`
4. In HA: Settings → Add-ons → BirdNET-PiPy → Check for updates → Update
5. Test both direct IP:port mode and ingress (sidebar) mode

### 4. Release

Once tested:

1. Bump BirdNET-PiPy version on `dev` following `VERSION_BUMP.md` (dev → staging → main → tag)
2. Sync `ha` with `dev` one final time (same `read-tree` command above)
3. Update `hassio-addon-birdnet-pipy` version to match (e.g., `0.6.2`), push `main`

### 5. Submit PR to alexbelgium/hassio-addons

Port only the actual fixes (not version bumps or test-specific changes) to Alex's repo:

```bash
cd hassio-addons
git fetch origin
git checkout -b fix/description origin/master

# Apply fixes to birdnet-pipy/ files
# Bump version in birdnet-pipy/config.yaml (triggers CI build)

git commit -m "fix(birdnet-pipy): description"
git push fork fix/description
gh pr create --repo alexbelgium/hassio-addons
```

The version bump in the PR is required — Alex's CI builds a new addon image when the version in `config.yaml` changes.

## Testing Checklist

When testing HA addon changes, verify both access modes:

- [ ] **Direct IP:port** — open `http://<ha-ip>:8011` in browser
- [ ] **Ingress (sidebar)** — open via HA sidebar → BirdNET-PiPy

For each mode, check:
- [ ] Dashboard loads, bird images display
- [ ] Navigation works (all nav links, FAB clicks)
- [ ] Live Feed: stream sources load, audio plays
- [ ] Settings page loads, recorder status shows
- [ ] Login/auth flows work (if auth enabled)

## Common HA-Specific Issues

**Permission errors in s6 services**: `cont-init.d/` runs as root but `services.d/` may drop privileges. If a service writes to a root-created directory, add `chown` before `gosu`.

**Ingress double-prefix**: `sub_filter` rules can match unintended strings in JS bundles. Prefer making frontend paths relative (resolves via `<base href>`) over adding new sub_filter rules.

**Ingress navigation**: Vue Router needs the ingress base path. Read it from `<base href>`:
```js
createWebHistory(document.querySelector('base')?.getAttribute('href') || '/')
```
