.DEFAULT_GOAL := help
SHELL         := bash
REPOS_FILE    := repos.yaml
PARENT_DIR    := $(CURDIR)/repos
THIS_REPO     := $(shell basename $(CURDIR))
AGENTS_FILE   := ai/AGENTS.md

# Farger
BOLD  := \033[1m
RESET := \033[0m
GREEN := \033[32m
CYAN  := \033[36m

.PHONY: help clone fetch pull main status add-repo setup docs

##@ Hjelp

help: ## Vis alle tilgjengelige kommandoer
	@awk 'BEGIN {FS = ":.*##"; printf "\n$(BOLD)Bruk:$(RESET)\n  make $(CYAN)<kommando>$(RESET)\n"} \
	  /^[a-zA-Z_-]+:.*?##/ { printf "  $(CYAN)%-18s$(RESET) %s\n", $$1, $$2 } \
	  /^##@/ { printf "\n$(BOLD)%s$(RESET)\n", substr($$0, 5) }' $(MAKEFILE_LIST)

##@ Repo-administrasjon

clone: _require-yq ## Klon alle repos fra repos.yaml til ./repos/
	@echo -e "$(BOLD)Kloner alle repos til $(PARENT_DIR)/$(RESET)"
	@mkdir -p $(PARENT_DIR)
	@yq e '.repos[] | select(.managed == true) | .org + "/" + .name' $(REPOS_FILE) | while read repo; do \
	  name=$$(echo $$repo | cut -d/ -f2); \
	  dest=$(PARENT_DIR)/$$name; \
	  [ "$$dest" = "$(CURDIR)" ] && { echo -e "  ⏭  $$name — dette repoet, skipper"; continue; }; \
	  if [ -d "$$dest/.git" ]; then \
	    echo -e "  $(GREEN)↓$(RESET) $$name — finnes allerede, skipper"; \
	  else \
	    echo -e "  $(GREEN)+$(RESET) Kloner $$repo → $$dest"; \
	    git clone git@github.com:$$repo.git $$dest 2>&1 | grep -v "^remote:" | grep -v "^Receiving\|^Resolving\|^Compressing" || \
	      echo -e "    ⚠️  Kunne ikke klone $$repo — sjekk org-felt i repos.yaml"; \
	  fi \
	done

fetch: _require-yq ## Kjør git fetch --all på alle repos
	@echo -e "$(BOLD)Fetcher alle repos$(RESET)"
	@yq e '.repos[] | .name' $(REPOS_FILE) | while read name; do \
	  dir=$(PARENT_DIR)/$$name; \
	  [ -d "$$dir/.git" ] || { echo "  ⚠️  $$name ikke klonet — kjør 'make clone'"; continue; }; \
	  echo -e "  $(CYAN)↻$(RESET) $$name"; \
	  git -C $$dir fetch --all --prune --quiet; \
	done

pull: _require-yq ## Kjør git pull på alle repos (kun main/master, hopper over dirty)
	@echo -e "$(BOLD)Puller alle repos$(RESET)"
	@yq e '.repos[] | .name + " " + .default_branch' $(REPOS_FILE) | while read name branch; do \
	  dir=$(PARENT_DIR)/$$name; \
	  [ -d "$$dir/.git" ] || { echo "  ⚠️  $$name ikke klonet — kjør 'make clone'"; continue; }; \
	  if ! git -C $$dir diff --quiet || ! git -C $$dir diff --cached --quiet; then \
	    echo -e "  ⚠️  $$name — har uncommitted endringer, skipper"; \
	    continue; \
	  fi; \
	  current=$$(git -C $$dir branch --show-current); \
	  if [ "$$current" = "$$branch" ]; then \
	    echo -e "  $(GREEN)↓$(RESET) $$name ($$branch)"; \
	    git -C $$dir pull --quiet; \
	  else \
	    echo -e "  ⏭  $$name — på branch '$$current', skipper pull"; \
	  fi \
	done

main: _require-yq ## Switch til main + pull på alle repos
	@echo -e "$(BOLD)Bytter til main og puller alle repos$(RESET)"
	@yq e '.repos[] | .name + " " + .default_branch' $(REPOS_FILE) | while read name branch; do \
	  dir=$(PARENT_DIR)/$$name; \
	  [ -d "$$dir/.git" ] || { echo "  ⚠️  $$name ikke klonet — kjør 'make clone'"; continue; }; \
	  if git -C $$dir diff --quiet && git -C $$dir diff --cached --quiet; then \
	    echo -e "  $(GREEN)→$(RESET) $$name: checkout $$branch + pull"; \
	    git -C $$dir checkout $$branch --quiet && git -C $$dir pull --quiet; \
	  else \
	    echo -e "  ⚠️  $$name — har uncommitted endringer, skipper"; \
	  fi \
	done

status: _require-yq ## Vis branch, dirty, commits bak remote og parent POM-versjon
	@echo -e "$(BOLD)Status for alle repos$(RESET)"
	@{ \
	  printf "REPO\tBRANCH\tDIRTY\tBEHIND\tPARENT POM\n"; \
	  printf "%s\t%s\t%s\t%s\t%s\n" "----" "------" "-----" "------" "----------"; \
	  yq e '.repos[] | .name + " " + .default_branch' $(REPOS_FILE) | while read name branch; do \
	    dir=$(PARENT_DIR)/$$name; \
	    if [ ! -d "$$dir/.git" ]; then \
	      printf "%s\t%s\t%s\t%s\t%s\n" "$$name" "—" "—" "—" "❌ ikke klonet"; \
	      continue; \
	    fi; \
	    current=$$(git -C $$dir branch --show-current 2>/dev/null || echo "detached"); \
	    if git -C $$dir diff --quiet && git -C $$dir diff --cached --quiet; then \
	      dirty="✅"; \
	    else \
	      dirty="⚠️"; \
	    fi; \
	    behind=$$(git -C $$dir rev-list HEAD..origin/$$branch --count 2>/dev/null); \
	    if [ -z "$$behind" ]; then behind_str="?"; \
	    elif [ "$$behind" = "0" ]; then behind_str="✅"; \
	    else behind_str="$$behind ↓"; fi; \
	    if [ -f "$$dir/pom.xml" ]; then \
	      parent_ver=$$(grep -A3 '<parent>' $$dir/pom.xml | grep '<version>' | head -1 | sed 's/.*<version>\(.*\)<\/version>.*/\1/' | tr -d ' '); \
	      [ -z "$$parent_ver" ] && parent_ver="—"; \
	    else \
	      parent_ver="—"; \
	    fi; \
	    printf "%s\t%s\t%s\t%s\t%s\n" "$$name" "$$current" "$$dirty" "$$behind_str" "$$parent_ver"; \
	  done; \
	} | python3 scripts/fmt-table.py

versions: _require-yq ## Vis avhengighetsversjoner på tvers av alle repos
	@echo -e "$(BOLD)Versjoner på tvers av repos$(RESET)"
	@{ \
	  printf "REPO\tJAVA\tPARENT POM\tKOTLIN\tTOKEN-VAL\tHIBERNATE\tPOSTGRES\tTOMCAT\tNODE\tPNPM\tAKSEL\n"; \
	  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" "----" "----" "----------" "------" "---------" "---------" "--------" "------" "----" "----" "-----"; \
	  yq e '.repos[] | .name' $(REPOS_FILE) | while read name; do \
	    dir=$(PARENT_DIR)/$$name; \
	    [ -d "$$dir" ] || continue; \
	    java_ver="—"; parent_ver="—"; kotlin_ver="—"; token_ver="—"; hibernate_ver="—"; pg_ver="—"; tomcat_ver="—"; node_ver="—"; pnpm_ver="—"; aksel_ver="—"; \
	    if [ -f "$$dir/pom.xml" ]; then \
	      java_ver=$$(grep -m1 '<java.version>\|<maven.compiler.source>' $$dir/pom.xml | sed 's/.*>\(.*\)<.*/\1/' | tr -d ' ' | head -1); \
	      [ -z "$$java_ver" ] && java_ver="—"; \
	      parent_ver=$$(grep -A3 '<parent>' $$dir/pom.xml | grep '<version>' | head -1 | sed 's/.*<version>\(.*\)<\/version>.*/\1/' | tr -d ' '); \
	      [ -z "$$parent_ver" ] && parent_ver="—"; \
	      kotlin_ver=$$(grep '<kotlin.version>' $$dir/pom.xml | head -1 | sed 's/.*>\(.*\)<.*/\1/' | tr -d ' '); \
	      [ -z "$$kotlin_ver" ] && kotlin_ver="(BOM)"; \
	      token_ver=$$(grep '<token-validation.version>' $$dir/pom.xml | head -1 | sed 's/.*>\(.*\)<.*/\1/' | tr -d ' '); \
	      [ -z "$$token_ver" ] && token_ver="(BOM)"; \
	      hibernate_ver=$$(grep '<hibernate.version>' $$dir/pom.xml | head -1 | sed 's/.*>\(.*\)<.*/\1/' | tr -d ' '); \
	      [ -z "$$hibernate_ver" ] && hibernate_ver="(BOM)"; \
	      pg_ver=$$(grep '<postgresql.version>' $$dir/pom.xml | head -1 | sed 's/.*>\(.*\)<.*/\1/' | tr -d ' '); \
	      [ -z "$$pg_ver" ] && pg_ver="(BOM)"; \
	      tomcat_ver=$$(grep '<tomcat.version>' $$dir/pom.xml | head -1 | sed 's/.*>\(.*\)<.*/\1/' | tr -d ' '); \
	      [ -z "$$tomcat_ver" ] && tomcat_ver="(BOM)"; \
	    fi; \
	    pkg=$$(grep -rl '@navikt/ds-react' "$$dir" --include="package.json" 2>/dev/null | grep -v node_modules | head -1); \
	    [ -z "$$pkg" ] && pkg=$$(find "$$dir" -name "package.json" -not -path "*/node_modules/*" -not -path "*/e2e/*" 2>/dev/null | head -1); \
	    if [ -n "$$pkg" ]; then \
	      pkgdir=$$(dirname $$pkg); \
	      node_ver=$$(python3 -c "import json; d=json.load(open('$$pkg')); print(d.get('engines',{}).get('node','—'))" 2>/dev/null || echo "—"); \
	      [ -f "$$pkgdir/.nvmrc" ] && node_ver=$$(cat $$pkgdir/.nvmrc | tr -d 'v\n'); \
	      [ -z "$$node_ver" ] || [ "$$node_ver" = "None" ] && node_ver="—"; \
	      pnpm_ver=$$(python3 -c "import json; d=json.load(open('$$pkg')); pm=d.get('packageManager',''); v=pm.split('@')[1] if '@' in pm and 'pnpm' in pm else '—'; print(v.split('+')[0])" 2>/dev/null || echo "—"); \
	      aksel_ver=$$(python3 -c "import json; d=json.load(open('$$pkg')); deps={**d.get('dependencies',{}),**d.get('devDependencies',{})}; print(deps.get('@navikt/ds-react','—').lstrip('^~'))" 2>/dev/null || echo "—"); \
	    fi; \
	    printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" "$$name" "$$java_ver" "$$parent_ver" "$$kotlin_ver" "$$token_ver" "$$hibernate_ver" "$$pg_ver" "$$tomcat_ver" "$$node_ver" "$$pnpm_ver" "$$aksel_ver"; \
	  done; \
	} | python3 scripts/fmt-table.py

##@ Legg til repo

add-repo: _require-yq ## Registrer nytt repo  — bruk: make add-repo ORG=navikt REPO=navn DESC="beskrivelse"
ifndef ORG
	$(error ORG mangler. Bruk: make add-repo ORG=navikt REPO=navn DESC="beskrivelse")
endif
ifndef REPO
	$(error REPO mangler. Bruk: make add-repo ORG=navikt REPO=navn DESC="beskrivelse")
endif
	@DESC=$${DESC:-"Ingen beskrivelse"}; \
	if yq e '.repos[] | .name' $(REPOS_FILE) | grep -q "^$(REPO)$$"; then \
	  echo -e "  ⚠️  $(REPO) er allerede registrert i $(REPOS_FILE)"; \
	else \
	  yq e -i '.repos += [{"name": "$(REPO)", "org": "$(ORG)", "description": "'"$$DESC"'", "stack": [], "default_branch": "main"}]' $(REPOS_FILE); \
	  echo -e "  $(GREEN)+$(RESET) $(REPO) lagt til i $(REPOS_FILE)"; \
	  $(MAKE) docs; \
	fi

##@ Masseoppdateringer

update-kotlin: _require-yq ## Oppdater kotlin.version + Dependabot i alle repos  — bruk: make update-kotlin VERSION=2.x.y
ifndef VERSION
	$(error VERSION mangler. Bruk: make update-kotlin VERSION=2.x.y)
endif
	@echo -e "$(BOLD)Oppdaterer kotlin.version til $(VERSION) i alle repos$(RESET)"
	@yq e '.repos[] | select(.managed == true) | .name + " " + .default_branch' $(REPOS_FILE) | while read name branch; do \
	  dir=$(PARENT_DIR)/$$name; \
	  [ -f "$$dir/pom.xml" ] || continue; \
	  current=$$(grep '<kotlin.version>' $$dir/pom.xml | head -1 | sed 's/.*>\(.*\)<.*/\1/' | tr -d ' '); \
	  [ -z "$$current" ] && { echo -e "  ⏭  $$name — ingen kotlin.version, skipper"; continue; }; \
	  [ "$$current" = "$(VERSION)" ] && { echo -e "  ✅ $$name — allerede på $(VERSION)"; continue; }; \
	  if ! git -C $$dir diff --quiet || ! git -C $$dir diff --cached --quiet; then \
	    echo -e "  ⚠️  $$name — har uncommitted endringer, skipper"; continue; \
	  fi; \
	  git -C $$dir checkout $$branch --quiet && git -C $$dir pull --quiet; \
	  git -C $$dir checkout -b "chore/kotlin-$(VERSION)" --quiet 2>/dev/null || \
	    git -C $$dir checkout "chore/kotlin-$(VERSION)" --quiet; \
	  sed -i '' "s|<kotlin.version>$$current</kotlin.version>|<kotlin.version>$(VERSION)</kotlin.version>|g" $$dir/pom.xml; \
	  git -C $$dir add pom.xml; \
	  if [ -f "$$dir/.github/dependabot.yml" ]; then \
	    sed -i '' "s|kotlin-.*|kotlin-$(VERSION)|g" $$dir/.github/dependabot.yml 2>/dev/null || true; \
	    grep -q 'jetbrains.kotlin\|kotlin-stdlib' $$dir/.github/dependabot.yml 2>/dev/null && \
	      git -C $$dir add .github/dependabot.yml; \
	  fi; \
	  git -C $$dir diff --cached --quiet && { echo -e "  ⏭  $$name — ingen endringer å committe"; continue; }; \
	  git -C $$dir commit -m "chore: bump kotlin.version $$current -> $(VERSION)" --quiet; \
	  git -C $$dir push -u origin "chore/kotlin-$(VERSION)" --quiet; \
	  repo_slug=$$(git -C $$dir remote get-url origin | sed 's/.*github.com[:/]\(.*\)\.git/\1/'); \
	  gh pr create --repo $$repo_slug \
	    --title "chore: bump Kotlin $$current → $(VERSION)" \
	    --body "Oppdaterer \`kotlin.version\` fra \`$$current\` til \`$(VERSION)\`." \
	    --base $$branch && \
	    echo -e "  $(GREEN)+$(RESET) $$name: PR opprettet ($$current → $(VERSION))" || \
	    echo -e "  $(GREEN)→$(RESET) $$name: pushet branch chore/kotlin-$(VERSION)"; \
	done

##@ Dokumentasjon

docs: ## Regenerer ai/AGENTS.md fra repos.yaml
	@echo -e "$(BOLD)Regenererer $(AGENTS_FILE)$(RESET)"
	@python3 scripts/gen-agents.py $(REPOS_FILE) $(AGENTS_FILE)
	@echo -e "  $(GREEN)✓$(RESET) $(AGENTS_FILE) oppdatert"


##@ Oppsett

setup: ## Installer verktøy på ny maskin (macOS)
	@echo -e "$(BOLD)Setter opp ny maskin$(RESET)"
	@command -v brew >/dev/null || { echo "Installerer Homebrew..."; /bin/bash -c "$$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"; }
	@echo -e "  $(CYAN)→$(RESET) Installerer verktøy via Homebrew..."
	@brew install yq git gh nais/tap/nais 2>/dev/null || true
	@brew install --cask temurin 2>/dev/null || true
	@echo -e "  $(GREEN)✓$(RESET) Verktøy installert"
	@echo -e "  $(CYAN)→$(RESET) Logger inn på GitHub CLI..."
	@gh auth status >/dev/null 2>&1 || gh auth login
	@echo ""
	@echo -e "$(GREEN)$(BOLD)Alt klart! Kjør 'make clone' for å klone alle repos.$(RESET)"

##@ Internalt

_require-yq:
	@command -v yq >/dev/null || { echo "❌ yq ikke installert — kjør 'make setup' eller 'brew install yq'"; exit 1; }
