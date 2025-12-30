# Git Workflow

## Branch Strategy

- `dev` - Main development branch
- `staging` - Mirrors dev, used for testing
- `main` - Clean history for public release (squashed commits)

## Workflow Steps

### 1. Commit on dev
```bash
git add -A
git commit -m "feat: description"
```

### 2. Merge to staging
```bash
git checkout staging
git merge dev --ff-only
```

### 3. Push dev and staging
```bash
git push origin dev staging
```

### 4. Squash-sync to main
```bash
git checkout main
git rm -rf .
git checkout staging -- .
git commit -m "summarized commit message"
```

### 5. Push main
```bash
git push origin main
git push public main
```

### 6. Return to dev
```bash
git checkout dev
```

## Notes

- Main has different history than dev/staging (squashed)
- The `git rm -rf . && git checkout staging -- .` pattern syncs all changes including deletions
- Write a summary commit message for main that covers all changes since last sync
