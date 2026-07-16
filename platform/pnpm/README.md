# @navikt/infotek-frontend-config

Delte konfigurasjoner og versjonskataloget for infotek sine frontend-prosjekter.

Publisert på GitHub Packages: `https://npm.pkg.github.com`

## Innhold

| Fil | Bruk |
|-----|------|
| `tsconfig.base.json` | Felles TypeScript-konfig |
| `biome.base.json` | Felles Biome-regler |

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

Versjonene for alle frontend-avhengigheter ligger i `dependencies` og `devDependencies` i `package.json`.
Dependabot i hvert repo bumper avhengighetene direkte og lager PRer automatisk.

## Publisering

```bash
make release-npm VERSION=1.0.0
```
