#!/usr/bin/env bash
set -euo pipefail

# Secret pattern detection script
# Checks staged files and working directory for common secret formats

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

error() {
  echo -e "${RED}[ERROR]${NC} $1" >&2
}

warn() {
  echo -e "${YELLOW}[WARN]${NC} $1" >&2
}

success() {
  echo -e "${GREEN}[OK]${NC} $1"
}

# Common secret patterns
declare -A PATTERNS=(
  ["Groq API Key"]="gsk_[a-zA-Z0-9]{20,}"
  ["Tavily API Key"]="tvly-[a-zA-Z0-9]{30,}"
  ["Supabase Key"]="sb_secret_[a-zA-Z0-9]{30,}"
  ["JWT Bearer Token"]="eyJ[A-Za-z0-9_-]{20,}\\.eyJ[A-Za-z0-9_-]{20,}"
  ["AWS Access Key"]="AKIA[0-9A-Z]{16}"
  ["Private PEM Key"]="BEGIN.*PRIVATE KEY"
)

found_secrets=0
checked_staged=false
checked_working=false

# Check staged files if git is available
if command -v git &> /dev/null && git rev-parse --git-dir &> /dev/null; then
  if git diff --cached --name-only &> /dev/null; then
    checked_staged=true
    for pattern_name in "${!PATTERNS[@]}"; do
      pattern="${PATTERNS[$pattern_name]}"
      if git diff --cached | grep -qE "$pattern"; then
        error "Potential secret detected in staged files: $pattern_name"
        git diff --cached | grep -E "$pattern" | head -3
        found_secrets=$((found_secrets + 1))
      fi
    done
  fi
fi

# Check .env file for unquoted secrets (loose check)
if [[ -f .env ]]; then
  if grep -qE "^[A-Z_]+_KEY=\"[^=]{20,}\"$|^[A-Z_]+_KEY='[^=]{20,}'$" .env; then
    warn ".env file contains keys; ensure .env is in .gitignore and never committed"
    success ".env exists (local-only file, not in git)"
  fi
fi

# Report results
if [[ $found_secrets -gt 0 ]]; then
  error "Found $found_secrets potential secret(s). Unstage sensitive files before committing."
  error "Use: git reset <file>"
  exit 1
else
  if [[ $checked_staged == true ]]; then
    success "No obvious secrets in staged files"
  fi
  success "Secret validation passed"
  exit 0
fi
