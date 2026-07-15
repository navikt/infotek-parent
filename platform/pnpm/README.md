# @navikt/infotek-frontend-config

Delte konfigurasjoner og versjonskataloget for infotek sine frontend-prosjekter.

Publisert på GitHub Packages: `https://npm.pkg.github.com`

## Innhold

| Fil | Bruk |
|-----|------|
| `tsconfig.base.json` | Felles TypeScript-konfig |
| `biome.base.json` | Felles Biome-regler |
| `catalog.json` | Godkjente versjoner for alle avhengigheter |

## Bruk i et prosjekt

Installer pakken:
```bash
pnpm add -D @navikt/infotek-frontend-config
```

### tsconfig.json
```json
{
  "extends": "@navikt/infotek-frontend-config/tsconfig.base.json",
  "compilerOptions": {
    "paths": {
      "~/*": ["./src/*"]
    },
    "types": ["vite/client", "node"]
  },
  "include": ["src", "vite-env.d.ts"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

### biome.json
```json
{
  "extends": ["@navikt/infotek-frontend-config/biome.base.json"]
}
```

## Versjonsstyring

Oppdater `catalog.json` med nye versjoner og kjør:
```bash
make update-frontend-deps
```

Dette lager PRer til alle frontend-repos med oppdaterte versjoner.

## Publisering

```bash
make release-frontend-config VERSION=1.1.0
```
