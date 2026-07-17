# Plan: Release @navikt/infotek-frontend-config@1.1.1

## Problem
CI feiler fordi vi patchet `node_modules` direkte i stedet for å release pakken.
- Publisert versjon: `1.1.0` — har gammel `biome.base.json` (lineWidth 100, ingen vite.config.d.ts-eksklusjon)
- Vår `platform/pnpm/biome.base.json`: korrekt (lineWidth 120, double/always, vite.config.d.ts ekskludert)
- CI installerer `1.1.0` → format-mismatch → ❌

## Løsning
Release `1.1.1` med riktig `biome.base.json`, oppdater alle repos, rerun biome:write uten node_modules-patching.

## Steg

### 1. Bump versjon i platform/pnpm/package.json
- `"version": "1.0.3"` → `"1.1.1"`

### 2. Commit + release
- `git add platform/pnpm/package.json`
- `git commit -m "chore: bump @navikt/infotek-frontend-config til 1.1.1"`
- `make pnpm-release VERSION=1.1.1`
- (Du bekrefter publisering interaktivt)

### 3. Oppdater alle repos til `^1.1.1`
- avstandskalkulator: `^1.0.0` → `^1.1.1`
- Resten: `^1.0.3` → `^1.1.1`
- Script oppdaterer `package.json` i alle 9 repos

### 4. Kjør `pnpm install` i alle repos
- Oppdaterer lockfiler til 1.1.1 (real, ikke patchet)

### 5. Rerun `biome check --write` i alle repos
- Nå mot ekte installert pakke, ingen node_modules-patching

### 6. Verifiser med `make pnpm-biome-check`

### 7. Commit og push
- Stage alle repos: `make git-stage-all`
- `make git-multi-commit MSG="chore: oppdater til @navikt/infotek-frontend-config@1.1.1"`
- `make git-push-all`

## Viktig
- infotek-parent endringer (Makefile, platform/pnpm) må committes på en branch + PR
- historisk-avstandskalkulator bruker `^1.0.0` (ikke `^1.0.3`) — must bump
