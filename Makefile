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

.PHONY: help git-clone git-fetch git-pull git-default git-status git-clean-branches git-stage-all git-multi-commit git-push-all git-merge-main gh-add-repo gh-apply-ruleset gh-detach-repo pr pr-lag pr-rerun mvn-versions mvn-update-kotlin mvn-release pnpm-versions pnpm-install pnpm-biome-check pnpm-update-npmrc pnpm-migrate-frontend-config pnpm-update-frontend-config pnpm-release docs update-readme setup

##@ Hjelp

help: ## Vis alle tilgjengelige kommandoer
	@awk 'BEGIN {FS = ":.*##"; printf "\n$(BOLD)Bruk:$(RESET)\n  make $(CYAN)<kommando>$(RESET)\n"} \
	  /^[a-zA-Z_-]+:.*?##/ { printf "  $(CYAN)%-18s$(RESET) %s\n", $$1, $$2 } \
	  /^##@/ { printf "\n$(BOLD)%s$(RESET)\n", substr($$0, 5) }' $(MAKEFILE_LIST)

##@ git — Grunnoperasjoner

git-clone: _require-yq ## Klon alle repos fra repos.yaml til ./repos/
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
	    gh repo clone $$repo $$dest 2>&1 | grep -v "^remote:" | grep -v "^Receiving\|^Resolving\|^Compressing" || \
	      echo -e "    ⚠️  Kunne ikke klone $$repo — sjekk at 'gh auth login' er kjørt"; \
	  fi \
	done

git-fetch: _require-yq ## Kjør git fetch --all på alle repos
	@echo -e "$(BOLD)Fetcher alle repos$(RESET)"
	@yq e '.repos[] | select(.managed == true) | .name' $(REPOS_FILE) | while read name; do \
	done

git-pull: _require-yq ## Kjør git pull på alle repos (kun main/master, hopper over dirty)
	@echo -e "$(BOLD)Puller alle repos$(RESET)"
	@yq e '.repos[] | select(.managed == true) | .name + " " + .default_branch' $(REPOS_FILE) | while read name branch; do \
	  dir=$(PARENT_DIR)/$$name; \
	  [ -d "$$dir/.git" ] || { echo "  ⚠️  $$name ikke klonet — kjør 'make git-clone'"; continue; }; \
	  if ! git -C $$dir diff --quiet || ! git -C $$dir diff --cached --quiet; then \
	    echo -e "  ⚠️  $$name — har uncommitted endringer, skipper"; \
	    continue; \
	  fi; \
	  current=$$(git -C $$dir branch --show-current); \
	  if [ "$$current" = "$$branch" ]; then \
	    echo -e "  $(GREEN)↓$(RESET) $$name (default: $$branch)"; \
	  else \
	    echo -e "  $(GREEN)↓$(RESET) $$name ($$current)"; \
	  fi; \
	  git -C $$dir pull --ff-only --quiet; \
	done

git-default: _require-yq ## Switch til default branch + pull på alle repos
	@echo -e "$(BOLD)Bytter til default branch og puller alle repos$(RESET)"
	@yq e '.repos[] | select(.managed == true) | .name + " " + .default_branch' $(REPOS_FILE) | while read name branch; do \
	  dir=$(PARENT_DIR)/$$name; \
	  [ -d "$$dir/.git" ] || { echo "  ⚠️  $$name ikke klonet — kjør 'make git-clone'"; continue; }; \
	  if git -C $$dir diff --quiet && git -C $$dir diff --cached --quiet; then \
	    echo -e "  $(GREEN)→$(RESET) $$name: checkout $$branch + pull"; \
	    git -C $$dir checkout $$branch --quiet && git -C $$dir pull --ff-only --quiet; \
	  else \
	    echo -e "  ⚠️  $$name — har uncommitted endringer, skipper"; \
	  fi \
	done

git-clean-branches: _require-yq ## Slett alle lokale branches som er merget til default branch
	@echo -e "$(BOLD)Sletter mergede lokale branches$(RESET)"
	@yq e '.repos[] | select(.managed == true) | .name + " " + .default_branch' $(REPOS_FILE) | while read name branch; do \
	  dir=$(PARENT_DIR)/$$name; \
	  [ -d "$$dir/.git" ] || { echo -e "  ⚠️  $$name ikke klonet — kjør 'make git-clone'"; continue; }; \
	  git -C $$dir fetch --prune --quiet; \
	  merged=$$(git -C $$dir branch --merged $$branch 2>/dev/null | grep -v "^\*\|^  $$branch$$" | sed 's/^[[:space:]]*//' | grep -v "^$$"); \
	  if [ -z "$$merged" ]; then \
	    echo -e "  $(GREEN)✓$(RESET) $$name — ingen branches å slette"; \
	  else \
	    echo -e "  $(CYAN)→$(RESET) $$name — sletter:"; \
	    echo "$$merged" | while read b; do \
	      git -C $$dir branch -d "$$b" --quiet && echo -e "    $(GREEN)-$(RESET) $$b"; \
	    done; \
	  fi \
	done

git-status: _require-yq ## Vis branch, dirty, commits bak remote og parent POM-versjon
	@echo -e "$(BOLD)Status for alle repos$(RESET)"
	@{ \
	  printf "REPO\tBRANCH\tDIRTY\tBEHIND\tPARENT POM\n"; \
	  printf "%s\t%s\t%s\t%s\t%s\n" "----" "------" "-----" "------" "----------"; \
	  yq e '.repos[] | select(.managed == true) | .name + " " + .default_branch' $(REPOS_FILE) | while read name branch; do \
	    dir=$(PARENT_DIR)/$$name; \
	    [ -d "$$dir" ] || continue; \
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

mvn-versions: _require-yq ## Vis Maven-versjoner på tvers av alle repos (Java, Kotlin, parent POM…)
	@echo -e "$(BOLD)Maven-versjoner på tvers av repos$(RESET)"
	@{ \
	  printf "REPO\tJAVA\tPARENT POM\tKOTLIN\tTOKEN-VAL\tHIBERNATE\tPOSTGRES\tTOMCAT\n"; \
	  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" "----" "----" "----------" "------" "---------" "---------" "--------" "------"; \
	  yq e '.repos[] | select(.managed == true) | .name' $(REPOS_FILE) | while read name; do \
	    dir=$(PARENT_DIR)/$$name; \
	    [ -f "$$dir/pom.xml" ] || continue; \
	    java_ver="—"; parent_ver="—"; kotlin_ver="—"; token_ver="—"; hibernate_ver="—"; pg_ver="—"; tomcat_ver="—"; \
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
	    printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" "$$name" "$$java_ver" "$$parent_ver" "$$kotlin_ver" "$$token_ver" "$$hibernate_ver" "$$pg_ver" "$$tomcat_ver"; \
	  done; \
	} | python3 scripts/fmt-table.py

pnpm-versions: _require-yq ## Vis frontend-versjoner på tvers av alle repos (Node, pnpm, Aksel)
	@echo -e "$(BOLD)Frontend-versjoner på tvers av repos$(RESET)"
	@{ \
	  printf "REPO\tNODE\tPNPM\tAKSEL\n"; \
	  printf "%s\t%s\t%s\t%s\n" "----" "----" "----" "-----"; \
	  yq e '.repos[] | select(.managed == true) | .name' $(REPOS_FILE) | while read name; do \
	    dir=$(PARENT_DIR)/$$name; \
	    pkg=$$(grep -rl '@navikt/ds-react' "$$dir" --include="package.json" 2>/dev/null | grep -v node_modules | head -1); \
	    [ -z "$$pkg" ] && pkg=$$(find "$$dir" -name "package.json" -not -path "*/node_modules/*" -not -path "*/e2e/*" 2>/dev/null | head -1); \
	    [ -z "$$pkg" ] && continue; \
	    pkgdir=$$(dirname $$pkg); \
	    node_ver=$$(python3 -c "import json; d=json.load(open('$$pkg')); print(d.get('engines',{}).get('node','—'))" 2>/dev/null || echo "—"); \
	    [ -f "$$pkgdir/.nvmrc" ] && node_ver=$$(cat $$pkgdir/.nvmrc | tr -d 'v\n'); \
	    [ -z "$$node_ver" ] || [ "$$node_ver" = "None" ] && node_ver="—"; \
	    pnpm_ver=$$(python3 -c "import json; d=json.load(open('$$pkg')); pm=d.get('packageManager',''); v=pm.split('@')[1] if '@' in pm and 'pnpm' in pm else '—'; print(v.split('+')[0])" 2>/dev/null || echo "—"); \
	    aksel_ver=$$(python3 -c "import json; d=json.load(open('$$pkg')); deps={**d.get('dependencies',{}),**d.get('devDependencies',{})}; print(deps.get('@navikt/ds-react','—').lstrip('^~'))" 2>/dev/null || echo "—"); \
	    printf "%s\t%s\t%s\t%s\n" "$$name" "$$node_ver" "$$pnpm_ver" "$$aksel_ver"; \
	  done; \
	} | python3 scripts/fmt-table.py

##@ gh — GitHub-administrasjon

gh-add-repo: _require-yq ## Registrer nytt repo  — bruk: make gh-add-repo ORG=navikt REPO=navn DESC="beskrivelse"
ifndef ORG
	$(error ORG mangler. Bruk: make gh-add-repo ORG=navikt REPO=navn DESC="beskrivelse")
endif
ifndef REPO
	$(error REPO mangler. Bruk: make gh-add-repo ORG=navikt REPO=navn DESC="beskrivelse")
endif
	@DESC=$${DESC:-"Ingen beskrivelse"}; \
	DEFAULT_BRANCH=$$(gh repo view $(ORG)/$(REPO) --json defaultBranchRef --jq '.defaultBranchRef.name' 2>/dev/null); \
	DEFAULT_BRANCH=$${DEFAULT_BRANCH:-main}; \
	if yq e '.repos[] | .name' $(REPOS_FILE) | grep -q "^$(REPO)$$"; then \
	  echo -e "  ⚠️  $(REPO) er allerede registrert i $(REPOS_FILE)"; \
	else \
	  yq e -i '.repos += [{"name": "$(REPO)", "org": "$(ORG)", "description": "'"$$DESC"'", "stack": [], "default_branch": "'"$$DEFAULT_BRANCH"'"}]' $(REPOS_FILE); \
	  echo -e "  $(GREEN)+$(RESET) $(REPO) lagt til i $(REPOS_FILE) (branch: $$DEFAULT_BRANCH)"; \
	  $(MAKE) docs; \
	fi

gh-detach-repo: ## Løsriv eit repo frå infotek — bruk: make gh-detach-repo REPO=<namn> [DRY_RUN=1]
ifndef REPO
	$(error REPO manglar. Bruk: make gh-detach-repo REPO=historisk-valutakalkulator)
endif
	@echo -e "$(BOLD)Løsriv $(REPO) frå infotek$(RESET)"
	@python3 scripts/detach-repo.py REPO=$(REPO) $(if $(DRY_RUN),--dry-run)

gh-apply-ruleset: ## Opprett eller oppdater branch-ruleset for et repo — bruk: make gh-apply-ruleset REPO=navikt/infotek-parent
ifndef REPO
	$(error REPO mangler. Bruk: make gh-apply-ruleset REPO=navikt/mitt-repo)
endif
	@echo -e "$(BOLD)Synkroniserer ruleset for $(REPO)$(RESET)"
	@existing=$$(gh api repos/$(REPO)/rulesets --jq '.[0].id' 2>/dev/null); \
	if [ -n "$$existing" ] && [ "$$existing" != "null" ]; then \
	  echo -e "  Ruleset finnes allerede (id $$existing) — vil du oppdatere?"; \
	  echo -n "  [j/N] " && read ans && case "$$ans" in \
	    [jJ]*) \
	      gh api repos/$(REPO)/rulesets/$$existing --method PUT --input platform/github/ruleset-default.json >/dev/null && \
	        echo -e "  $(GREEN)✓$(RESET) Ruleset oppdatert for $(REPO)" || \
	        echo -e "  ❌ Oppdatering feilet";; \
	    *) echo -e "  Avbrutt.";; \
	  esac; \
	else \
	  gh api repos/$(REPO)/rulesets --method POST --input platform/github/ruleset-default.json >/dev/null && \
	    echo -e "  $(GREEN)✓$(RESET) Ruleset opprettet for $(REPO)" || \
	    echo -e "  ❌ Oppretting feilet — sjekk at repoet finnes og at du har admin-tilgang"; \
	fi

##@ pr — Pull requests

pr: ## Behandle PRer interaktivt — velg modus ved oppstart — bruk: make pr [DRY_RUN=1]
	@python3 scripts/pr-behandle.py $(if $(DRY_RUN),--dry-run,)

pr-lag: ## Lag PRer interaktivt — velg repos, tittel og body — bruk: make pr-lag [BRANCH=navn]
	@python3 scripts/pr-all.py $(if $(BRANCH),BRANCH=$(BRANCH),)

pr-rerun: ## Rerun feilede CI-sjekker på åpne PRer — bruk: make pr-rerun [DRY_RUN=1]
	@python3 scripts/dependabot-rerun-failed.py $(if $(DRY_RUN),--dry-run,)

##@ git — Masseoperasjoner

git-stage-all: _require-yq ## Stage alle lokale endringer i alle repos (skipper default-branch) — bruk: make git-stage-all [ALLOW_DEFAULT=1]
	@echo -e "$(BOLD)Sjekker repos med lokale endringer$(RESET)\n"
	@tmpfile=$$(mktemp); \
	yq e '.repos[] | select(.managed == true) | .name + " " + .default_branch' $(REPOS_FILE) | while read name default_branch; do \
	  dir=$(PARENT_DIR)/$$name; \
	  [ -d "$$dir" ] || continue; \
	  changes=$$(git -C $$dir status --porcelain 2>/dev/null); \
	  [ -z "$$changes" ] && continue; \
	  branch=$$(git -C $$dir branch --show-current 2>/dev/null); \
	  if [ "$$branch" = "$$default_branch" ] && [ "$(ALLOW_DEFAULT)" != "1" ]; then \
	    echo -e "  ⚠️  $$name — på $$default_branch, skipper (bruk ALLOW_DEFAULT=1 for å overstyre)"; \
	    continue; \
	  fi; \
	  files=$$(echo "$$changes" | wc -l | tr -d ' '); \
	  echo -e "  $(CYAN)→$(RESET) $$name  [$$branch]  $$files fil(er)"; \
	  echo "$$name" >> $$tmpfile; \
	done; \
	echo ""; \
	if [ ! -s "$$tmpfile" ]; then \
	  echo -e "  Ingenting å stage."; \
	  rm -f $$tmpfile; \
	else \
	  count=$$(wc -l < $$tmpfile | tr -d ' '); \
	  echo -n "  Stage endringer i $$count repo(s)? [j/N] " && read ans && case "$$ans" in \
	    [jJ]*) \
	      while read name; do \
	        dir=$(PARENT_DIR)/$$name; \
	        git -C $$dir add -A; \
	        staged_count=$$(git -C $$dir diff --cached --name-only | wc -l | tr -d ' '); \
	        echo -e "  $(GREEN)✓$(RESET) $$name staged ($$staged_count filer)"; \
	      done < $$tmpfile; \
	      echo -e "\n$(CYAN)Tips:$(RESET) Kjør 'make git-multi-commit MSG=\"chore: ...\"' etter staging";; \
	    *) echo -e "  Avbrutt.";; \
	  esac; \
	  rm -f $$tmpfile; \
	fi

git-multi-commit: _require-yq ## Commit staged endringer i alle repos med samme melding — bruk: make git-multi-commit MSG="chore: ..."
ifndef MSG
	$(error MSG mangler. Bruk: make git-multi-commit MSG="chore: beskrivelse")
endif
	@echo -e "$(BOLD)Sjekker repos med staged endringer$(RESET)\n"
	@tmpfile=$$(mktemp); \
	yq e '.repos[] | select(.managed == true) | .name + " " + .default_branch' $(REPOS_FILE) | while read name default_branch; do \
	  dir=$(PARENT_DIR)/$$name; \
	  [ -d "$$dir" ] || continue; \
	  staged=$$(git -C $$dir diff --cached --name-only 2>/dev/null); \
	  [ -z "$$staged" ] && continue; \
	  branch=$$(git -C $$dir branch --show-current 2>/dev/null); \
	  if [ "$$branch" = "$$default_branch" ]; then \
	    echo -e "  ❌ $$name — på $$default_branch (protected). Lag branch først: git -C repos/$$name checkout -b chore/..."; \
	    continue; \
	  fi; \
	  files=$$(echo "$$staged" | wc -l | tr -d ' '); \
	  echo -e "  $(CYAN)→$(RESET) $$name  [$$branch]  $$files fil(er)"; \
	  echo "$$name" >> $$tmpfile; \
	done; \
	echo ""; \
	if [ ! -s "$$tmpfile" ]; then \
	  echo -e "  Ingenting å committe."; \
	  rm -f $$tmpfile; \
	else \
	  count=$$(wc -l < $$tmpfile | tr -d ' '); \
	  echo -n "  Commit i $$count repo(s)? [j/N] " && read ans && case "$$ans" in \
	    [jJ]*) \
	      while read name; do \
	        dir=$(PARENT_DIR)/$$name; \
	        branch=$$(git -C $$dir branch --show-current 2>/dev/null); \
	        staged=$$(git -C $$dir diff --cached --name-only 2>/dev/null); \
	        [ -z "$$staged" ] && continue; \
	        echo -e "  $(CYAN)→$(RESET) $$name ($$branch)"; \
	        echo "$$staged" | sed 's/^/      /'; \
	        git -C $$dir commit -m "$(MSG)" --quiet && \
	          echo -e "  $(GREEN)✓$(RESET) $$name committed" || \
	          echo -e "  ❌ $$name feilet"; \
	      done < $$tmpfile; \
	      echo -e "\n$(CYAN)Tips:$(RESET) Kjør 'make git-push-all' for å pushe alle branches";; \
	    *) echo -e "  Avbrutt.";; \
	  esac; \
	  rm -f $$tmpfile; \
	fi

git-push-all: _require-yq ## Push alle repos som er foran remote — spør om bekreftelse
	@echo -e "$(BOLD)Sjekker repos med upubliserte commits...$(RESET)\n"
	@tmpfile=$$(mktemp); \
	yq e '.repos[] | select(.managed == true) | .name + " " + .default_branch' $(REPOS_FILE) | while read name default_branch; do \
	  dir=$(PARENT_DIR)/$$name; \
	  [ -d "$$dir" ] || continue; \
	  branch=$$(git -C $$dir branch --show-current); \
	  upstream=$$(git -C $$dir rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || true); \
	  if [ -n "$$upstream" ]; then \
	    ahead=$$(git -C $$dir rev-list --count $$upstream..HEAD 2>/dev/null || echo 0); \
	  else \
	    ahead=$$(git -C $$dir rev-list --count origin/$$default_branch..HEAD 2>/dev/null || echo 0); \
	  fi; \
	  [ "$$ahead" = "0" ] && continue; \
	  if [ "$$branch" = "$$default_branch" ]; then \
	    echo -e "  ❌ $$name — på $$default_branch (protected, $$ahead commits)"; \
	    echo -e "     git -C repos/$$name checkout -b chore/... && git -C repos/$$name checkout $$default_branch && git -C repos/$$name reset --hard HEAD~$$ahead"; \
	  else \
	    echo -e "  $(CYAN)→$(RESET) $$name  [$$branch]  $$ahead commit(s)"; \
	    echo "$$name $$branch" >> $$tmpfile; \
	  fi; \
	done; \
	echo ""; \
	if [ ! -s "$$tmpfile" ]; then \
	  echo -e "  Ingenting å pushe."; \
	  rm -f $$tmpfile; \
	else \
	  count=$$(wc -l < $$tmpfile | tr -d ' '); \
	  echo -n "  Push $$count repo(s)? [j/N] " && read ans && case "$$ans" in \
	    [jJ]*) \
	      while read name branch; do \
	        git -C $(PARENT_DIR)/$$name push -u origin $$branch --quiet && \
	          echo -e "  $(GREEN)✓$(RESET) $$name  [$$branch]" || \
	          echo -e "  ❌ $$name feilet"; \
	      done < $$tmpfile;; \
	    *) echo -e "  Avbrutt.";; \
	  esac; \
	  rm -f $$tmpfile; \
	fi

git-merge-main: ## Merger default-branch inn i alle feature-branches på tvers av repos — bruk: make git-merge-main [DRY_RUN=1]
	@echo -e "$(BOLD)Merger default-branch inn i alle feature-branches$(RESET)"
	@if [ -n "$(DRY_RUN)" ]; then \
	  python3 scripts/merge-main.py --dry-run; \
	else \
	  echo -e "\n$(CYAN)Forhåndsvisning$(RESET)"; \
	  python3 scripts/merge-main.py --dry-run; \
	  echo ""; \
	  echo -n "  Kjør merge-main nå? [j/N] " && read ans && case "$$ans" in \
	    [jJ]*) python3 scripts/merge-main.py;; \
	    *) echo -e "  Avbrutt.";; \
	  esac; \
	fi

##@ mvn — Maven

mvn-release: ## Publiser ny versjon av Maven parent POM  — bruk: make mvn-release VERSION=1.0.0
ifndef VERSION
	$(error VERSION mangler. Bruk: make mvn-release VERSION=1.0.0)
endif
	@echo -e "$(BOLD)Tagger og publiserer Maven parent POM v$(VERSION)$(RESET)"
	@git diff --quiet && git diff --cached --quiet || { echo -e "  ⚠️  Har uncommitted endringer — commit først"; exit 1; }
	@echo -e "  Tag: v$(VERSION) → GitHub Packages (maven)"
	@echo -n "  Publiser? [j/N] " && read ans && case "$$ans" in \
	  [jJ]*) \
	    git tag "v$(VERSION)" -m "release: parent POM $(VERSION)"; \
	    git push origin "v$(VERSION)"; \
	    echo -e "  $(GREEN)✓$(RESET) Tag v$(VERSION) pushet — GitHub Actions publiserer til GitHub Packages";; \
	  *) echo -e "  Avbrutt.";; \
	esac

mvn-update-kotlin: _require-yq ## Oppdater kotlin.version + Dependabot i alle repos  — bruk: make mvn-update-kotlin VERSION=2.x.y
ifndef VERSION
	$(error VERSION mangler. Bruk: make mvn-update-kotlin VERSION=2.x.y)
endif
	@echo -e "$(BOLD)Sjekker repos som kan bumpes til Kotlin $(VERSION)$(RESET)"
	@yq e '.repos[] | select(.managed == true) | .name + " " + .default_branch' $(REPOS_FILE) | while read name branch; do \
	  dir=$(PARENT_DIR)/$$name; \
	  [ -f "$$dir/pom.xml" ] || continue; \
	  current=$$(grep '<kotlin.version>' $$dir/pom.xml | head -1 | sed 's/.*>\(.*\)<.*/\1/' | tr -d ' '); \
	  [ -z "$$current" ] && continue; \
	  [ "$$current" = "$(VERSION)" ] && { echo -e "  ✅ $$name — allerede på $(VERSION)"; continue; }; \
	  echo -e "  $(CYAN)→$(RESET) $$name  ($$current → $(VERSION))"; \
	done
	@echo -e ""
	@echo -n "  Bump og lag PRer? [j/N] " && read ans && case "$$ans" in \
	  [jJ]*) \
	    yq e '.repos[] | select(.managed == true) | .name + " " + .default_branch' $(REPOS_FILE) | while read name branch; do \
	      dir=$(PARENT_DIR)/$$name; \
	      [ -f "$$dir/pom.xml" ] || continue; \
	      current=$$(grep '<kotlin.version>' $$dir/pom.xml | head -1 | sed 's/.*>\(.*\)<.*/\1/' | tr -d ' '); \
	      [ -z "$$current" ] && continue; \
	      [ "$$current" = "$(VERSION)" ] && continue; \
	      if ! git -C $$dir diff --quiet || ! git -C $$dir diff --cached --quiet; then \
	        echo -e "  ⚠️  $$name — har uncommitted endringer, skipper"; continue; \
	      fi; \
	      git -C $$dir checkout $$branch --quiet && git -C $$dir pull --ff-only --quiet; \
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
	    done;; \
	  *) echo -e "  Avbrutt.";; \
	esac

##@ pnpm — Frontend

pnpm-migrate-frontend-config: ## Engangs-migrasjon: legg til infotek-frontend-config i alle repos — bruk: make pnpm-migrate-frontend-config [DRY_RUN=1]
	@echo -e "$(BOLD)Migrerer alle repos til @navikt/infotek-frontend-config$(RESET)"
	@if [ -n "$(DRY_RUN)" ]; then \
	  python3 scripts/migrate-frontend-config.py --dry-run; \
	else \
	  echo -e "\n$(CYAN)Forhåndsvisning$(RESET)"; \
	  python3 scripts/migrate-frontend-config.py --dry-run; \
	  echo ""; \
	  echo -n "  Kjør migrering nå? [j/N] " && read ans && case "$$ans" in \
	    [jJ]*) python3 scripts/migrate-frontend-config.py;; \
	    *) echo -e "  Avbrutt.";; \
	  esac; \
	fi

pnpm-update-frontend-config: ## Bump @navikt/infotek-frontend-config til versjon i katalogen i alle migrerte repos — bruk: make pnpm-update-frontend-config [DRY_RUN=1]
	@echo -e "$(BOLD)Bumper @navikt/infotek-frontend-config i alle frontend-repos$(RESET)"
	@if [ -n "$(DRY_RUN)" ]; then \
	  python3 scripts/update-frontend-config.py --dry-run; \
	else \
	  echo -e "\n$(CYAN)Forhåndsvisning$(RESET)"; \
	  python3 scripts/update-frontend-config.py --dry-run; \
	  echo ""; \
	  echo -n "  Kjør bump nå? [j/N] " && read ans && case "$$ans" in \
	    [jJ]*) python3 scripts/update-frontend-config.py;; \
	    *) echo -e "  Avbrutt.";; \
	  esac; \
	fi

pnpm-install: ## Kjør pnpm install i alle frontend-mapper på tvers av repos — bruk: make pnpm-install [DRY_RUN=1]
	@echo -e "$(BOLD)Kjører pnpm install i alle repos$(RESET)"
	@if [ -n "$(DRY_RUN)" ]; then \
	  python3 scripts/pnpm-install.py --dry-run; \
	else \
	  echo -e "\n$(CYAN)Forhåndsvisning$(RESET)"; \
	  python3 scripts/pnpm-install.py --dry-run; \
	  echo ""; \
	  echo -n "  Kjør pnpm install i alle funn nå? [j/N] " && read ans && case "$$ans" in \
	    [jJ]*) python3 scripts/pnpm-install.py;; \
	    *) echo -e "  Avbrutt.";; \
	  esac; \
	fi

pnpm-biome-check: ## Kjør Biome-sjekk og typesjekk i alle frontend-repos — spør om auto-fix ved feil. Bruk: make pnpm-biome-check [FIX=1]
	@if [ -n "$(FIX)" ]; then \
	  python3 scripts/pnpm-biome-check.py --fix; \
	else \
	  python3 scripts/pnpm-biome-check.py; \
	fi

pnpm-release: ## Publiser ny versjon av @navikt/infotek-frontend-config  — bruk: make pnpm-release VERSION=1.0.0
ifndef VERSION
	$(error VERSION mangler. Bruk: make pnpm-release VERSION=1.0.0)
endif
	@echo -e "$(BOLD)Tagger og publiserer @navikt/infotek-frontend-config v$(VERSION)$(RESET)"
	@git diff --quiet && git diff --cached --quiet || { echo -e "  ⚠️  Har uncommitted endringer — commit først"; exit 1; }
	@echo -e "  Tag: vfrontend-$(VERSION) → GitHub Packages (npm)"
	@echo -n "  Publiser? [j/N] " && read ans && case "$$ans" in \
	  [jJ]*) \
	    git tag "vfrontend-$(VERSION)" -m "release: frontend-config $(VERSION)"; \
	    git push origin "vfrontend-$(VERSION)"; \
	    echo -e "  $(GREEN)✓$(RESET) Tag vfrontend-$(VERSION) pushet — GitHub Actions publiserer til GitHub Packages";; \
	  *) echo -e "  Avbrutt.";; \
	esac

pnpm-update-npmrc: _require-yq ## Synkroniser .npmrc til teamstandard i alle repos — lager PR per repo
	@echo -e "$(BOLD)Sjekker .npmrc mot teamstandard$(RESET)"
	@TEMPLATE=$(CURDIR)/platform/npm/.npmrc; \
	needs_update_list=""; \
	yq e '.repos[] | select(.managed == true) | .name' $(REPOS_FILE) | while read name; do \
	  dir=$(PARENT_DIR)/$$name; \
	  [ -d "$$dir" ] || continue; \
	  for npmrc in $$(find "$$dir" -name ".npmrc" -not -path "*/node_modules/*" 2>/dev/null); do \
	    relpath=$$(echo "$$npmrc" | sed "s|^$$dir/||"); \
	    needs=0; \
	    grep -q "ignore-scripts=true" "$$npmrc" || needs=1; \
	    grep -q "min-release-age=7" "$$npmrc" || needs=1; \
	    grep -q "engine-strict=true" "$$npmrc" || needs=1; \
	    grep -q "npm.pkg.github.com" "$$npmrc" || needs=1; \
	    [ "$$needs" = "1" ] && echo -e "  $(CYAN)→$(RESET) $$name/$$relpath"; \
	  done; \
	done; \
	echo ""; \
	echo -n "  Oppdater og lag PRer? [j/N] " && read ans && case "$$ans" in \
	  [jJ]*) \
	    yq e '.repos[] | select(.managed == true) | .name + " " + .default_branch' $(REPOS_FILE) | while read name branch; do \
	      dir=$(PARENT_DIR)/$$name; \
	      [ -d "$$dir" ] || continue; \
	      changed=0; \
	      for npmrc in $$(find "$$dir" -name ".npmrc" -not -path "*/node_modules/*" 2>/dev/null); do \
	        relpath=$$(echo "$$npmrc" | sed "s|^$$dir/||"); \
	        needs=0; \
	        grep -q "ignore-scripts=true" "$$npmrc" || needs=1; \
	        grep -q "min-release-age=7" "$$npmrc" || needs=1; \
	        grep -q "engine-strict=true" "$$npmrc" || needs=1; \
	        grep -q "npm.pkg.github.com" "$$npmrc" || needs=1; \
	        if [ "$$needs" = "1" ]; then \
	          python3 scripts/merge-npmrc.py "$$TEMPLATE" "$$npmrc" && \
	            echo -e "  $(GREEN)✓$(RESET) $$name/$$relpath oppdatert"; \
	          changed=1; \
	        fi; \
	      done; \
	      [ "$$changed" = "0" ] && continue; \
	      if ! git -C $$dir diff --quiet || ! git -C $$dir diff --cached --quiet; then \
	        echo -e "  ⚠️  $$name — har andre uncommitted endringer, skipper push"; continue; \
	      fi; \
	      git -C $$dir checkout $$branch --quiet && git -C $$dir pull --ff-only --quiet; \
	      git -C $$dir checkout -b "chore/npmrc-teamstandard" --quiet 2>/dev/null || \
	        git -C $$dir checkout "chore/npmrc-teamstandard" --quiet; \
	      git -C $$dir add -A; \
	      git -C $$dir commit -m "chore: synkroniser .npmrc til teamstandard" --quiet; \
	      git -C $$dir push -u origin "chore/npmrc-teamstandard" --quiet; \
	      repo_slug=$$(git -C $$dir remote get-url origin | sed 's/.*github.com[:/]\(.*\)\.git/\1/'); \
	      gh pr create --repo $$repo_slug \
	        --title "chore: synkroniser .npmrc til teamstandard" \
	        --body "Legger til manglende innstillinger fra teamstandard:\n- \`ignore-scripts=true\`\n- \`min-release-age=7\`\n- \`engine-strict=true\`\n- \`@navikt:registry\`" \
	        --base $$branch && \
	        echo -e "  $(GREEN)+$(RESET) $$name: PR opprettet" || \
	        echo -e "  $(GREEN)→$(RESET) $$name: pushet branch chore/npmrc-teamstandard"; \
	    done;; \
	  *) echo -e "  Avbrutt.";; \
	esac

##@ Dokumentasjon

docs: ## Regenerer ai/AGENTS.md fra repos.yaml
	@echo -e "$(BOLD)Regenererer $(AGENTS_FILE)$(RESET)"
	@python3 scripts/gen-agents.py $(REPOS_FILE) $(AGENTS_FILE)
	@echo -e "  $(GREEN)✓$(RESET) $(AGENTS_FILE) oppdatert"

update-readme: ## Regenerer repo-oversikt i README.md fra repos.yaml (henter beskrivelser fra GitHub)
	@echo -e "$(BOLD)Regenererer repo-oversikt i README.md$(RESET)"
	@python3 scripts/gen-readme-repos.py $(REPOS_FILE) README.md
	@echo -e "  $(GREEN)✓$(RESET) README.md oppdatert"

##@ Oppsett

setup: ## Installer verktøy på ny maskin (macOS)
	@echo -e "$(BOLD)Setter opp ny maskin$(RESET)"
	@command -v brew >/dev/null || { echo "Installerer Homebrew..."; /bin/bash -c "$$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"; }
	@echo -e "  $(CYAN)→$(RESET) Installerer verktøy via Homebrew..."
	@brew install yq git gh nais/tap/nais 2>/dev/null || true
	@brew install --cask temurin 2>/dev/null || true
	@brew install navikt/tap/cplt navikt/tap/nav-pilot 2>/dev/null || true
	@echo -e "  $(CYAN)→$(RESET) Oppgraderer verktøy..."
	@brew upgrade yq git gh nais navikt/tap/cplt navikt/tap/nav-pilot 2>/dev/null || true
	@brew upgrade --cask temurin 2>/dev/null || true
	@echo -e "  $(GREEN)✓$(RESET) Verktøy installert"
	@echo -e "  $(CYAN)→$(RESET) Sikkerhetsinnstillinger for npm/pnpm..."
	@echo -e "  Vil du legge til teamstandard i ~/.npmrc? (ignore-scripts, min-release-age=7, engine-strict)"
	@echo -n "  [j/N] " && read ans && case "$$ans" in \
	  [jJ]*) python3 scripts/merge-npmrc.py platform/npm/.npmrc $$HOME/.npmrc 2>/dev/null || \
	    cp platform/npm/.npmrc $$HOME/.npmrc; \
	    echo -e "  $(GREEN)✓$(RESET) ~/.npmrc oppdatert";; \
	  *) echo -e "  ⏭  Hopper over — kan gjøres manuelt: python3 scripts/merge-npmrc.py platform/npm/.npmrc ~/.npmrc";; \
	esac
	@echo -e "  $(CYAN)→$(RESET) pnpm brukerkonfig (minimumReleaseAge, ignore-scripts)..."
	@echo -e "  Vil du sette teamstandard pnpm-konfig globalt?"
	@echo -e "  (minimumReleaseAge=1440, ignore-scripts, engine-strict)"
	@echo -n "  [j/N] " && read ans && case "$$ans" in \
	  [jJ]*) \
	    pnpm config set minimumReleaseAge 1440 --location=user 2>/dev/null && \
	    pnpm config set ignore-scripts true --location=user 2>/dev/null && \
	    pnpm config set engine-strict true --location=user 2>/dev/null && \
	    echo -e "  $(GREEN)✓$(RESET) pnpm brukerkonfig oppdatert" || \
	    echo -e "  ⚠️  pnpm ikke funnet — installer med: brew install pnpm";; \
	  *) echo -e "  ⏭  Hopper over — kan gjøres manuelt: pnpm config set minimumReleaseAge 1440 --location=user";; \
	esac
	@echo -e "  $(CYAN)→$(RESET) Logger inn på GitHub CLI..."
	@gh auth status >/dev/null 2>&1 || gh auth login
	@echo -e ""
	@echo -e "$(GREEN)$(BOLD)Alt klart! Kjør 'make git-clone' for å klone alle repos.$(RESET)"

##@ Internalt

_require-yq:
	@command -v yq >/dev/null || { echo "❌ yq ikke installert — kjør 'make setup' eller 'brew install yq'"; exit 1; }
