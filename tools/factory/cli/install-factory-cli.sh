#!/usr/bin/env bash
# Install the global `factory` command on this device (docs/factory-cli.md#install).
#
# Stage 1 (this script) checks the prerequisites and takes the initial configuration from a production branch: the one
# GitHub protects with the admin-managed "Factory production: <branch>" ruleset, or the one chosen among several (or
# --config-branch); without such a ruleset yet, from the remote default branch. It follows a finished change of the
# config branch once, refuses to run unless it is byte-identical to the copy on the config branch, and clones the
# control checkout on the control branch (--branch, default: the config branch) if it is missing. Stage 2 runs from
# that control checkout:
#   factory.py _install  (tools/factory/cli/install.py)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repo="$(git -C "$here" rev-parse --show-toplevel)"
parent="$(dirname "$repo")"
control="$parent/aicepeak-control-checkout"
candidate="$parent/aicepeak-candidate"
bin="$HOME/.local/bin"
keys=""
branch=""
start=""

usage() {
  cat <<EOF
Usage: $0 [--control-dir DIR] [--candidate-dir DIR] [--bin-dir DIR] [--branch NAME] [--config-branch NAME] [--author-keys]

  --control-dir DIR    control checkout (default: $control)
  --candidate-dir DIR  candidate checkout; an existing clone is reused (default: $candidate)
  --bin-dir DIR        where the factory command goes (default: $bin)
  --branch NAME        listed branch whose factory code this device runs (default: the config branch)
  --config-branch NAME production branch to take the initial configuration from (default: the one GitHub
                       protects as production; asked when there are several)
  --author-keys        (re)store the Anthropic and Context7 API keys in the macOS keychain
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --control-dir) control="$2"; shift 2 ;;
    --candidate-dir) candidate="$2"; shift 2 ;;
    --bin-dir) bin="$2"; shift 2 ;;
    --branch) branch="$2"; shift 2 ;;
    --config-branch) start="$2"; shift 2 ;;
    --author-keys) keys="--author-keys"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for tool in git gh python3; do
  command -v "$tool" >/dev/null 2>&1 || { echo "missing $tool: see docs/dev-setup.md" >&2; exit 1; }
done
python="$(command -v python3)"
"$python" -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo "Python 3.11 or newer is required" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || echo "note: gh is not logged in; most factory commands need \`gh auth login\`" >&2

# Fixed here, so the byte-identity check below also covers where the control checkout comes from.
repository="Zerosteps1/Aicepeak_V2.0.0"
configured="$("$python" -I -c '
import json, sys
try:
    print(json.load(open(sys.argv[1]))["repository"])
except (OSError, ValueError, KeyError, TypeError):
    sys.exit(f"cannot read the repository from {sys.argv[1]}: run the installer of a factory checkout")
' "$repo/factory/config.json")"
[ "$configured" = "$repository" ] || { echo "factory/config.json names $configured, not $repository; refusing" >&2; exit 1; }
url="https://github.com/$repository.git"
self="tools/factory/cli/install-factory-cli.sh"
name_pattern='^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$'
safe_git() { git -c core.hooksPath=/dev/null -c core.fsmonitor=false "$@"; }

# Before the owner runbook of ADR-0008, GitHub's default branch still carries the configuration without a branch model.
not_yet="GitHub does not carry the branch model of FACTORY-008 yet, and the installer installs only what GitHub's config \
branch carries: finish the owner runbook in docs/decisions/0008-branch-model.md (land the change, rename the default \
branch, create the config branch), then retry"

fetch_branch() {  # fetch_branch DIR NAME [WHY]: refs/remotes/origin/NAME, fails when GitHub has no such branch
  safe_git -C "$1" fetch --quiet --no-tags "$url" "+refs/heads/$2:refs/remotes/origin/$2" \
    || { echo "cannot fetch branch $2 from $url${3:+: $3}" >&2; exit 1; }
}

config_of() {  # config_of NAME: factory/config.json of origin/NAME
  safe_git -C "$repo" cat-file -e "refs/remotes/origin/$1:factory/config.json" 2>/dev/null \
    || { echo "origin/$1 has no factory/config.json: $not_yet" >&2; exit 1; }
  safe_git -C "$repo" cat-file blob "refs/remotes/origin/$1:factory/config.json"
}

named_by() {  # named_by NAME CONFIG: the config branch that configuration names, or why there is none
  "$python" -I -c '
import json, sys
name, text, hint = sys.argv[1:]
try:
    data = json.loads(text)
except ValueError:
    sys.exit(f"factory/config.json on {name} is not valid JSON")
value = data.get("config_branch") if isinstance(data, dict) else None
if not isinstance(value, str) or not value:
    sys.exit(f"factory/config.json on {name} names no config branch (config_branch): {hint}")
print(value)
' "$1" "$2" "$not_yet"
}

protected_branches() {  # the branches GitHub protects with an active "Factory production: <branch>" ruleset
  local rulesets id name
  rulesets="$(gh api "repos/$repository/rulesets?per_page=100" 2>/dev/null || true)"
  printf '%s' "$rulesets" | "$python" -I -c '
import json, sys
try:
    prefix, suffix = json.load(open(sys.argv[1]))["ruleset_names"]["production"].split("{branch}")
    rulesets = json.load(sys.stdin)
except (OSError, ValueError, KeyError, TypeError, AttributeError):
    sys.exit(0)  # no readable rulesets: the default branch names the config branch
for ruleset in rulesets if isinstance(rulesets, list) else []:
    name = ruleset.get("name") if isinstance(ruleset, dict) else None
    if isinstance(name, str) and name.startswith(prefix) and name.endswith(suffix) and len(name) > len(prefix + suffix):
        print(ruleset.get("id"), name[len(prefix):len(name) - len(suffix)])
' "$repo/factory/github-settings.json" | while read -r id name; do
    [[ $id =~ ^[1-9][0-9]*$ && $name =~ $name_pattern ]] || continue
    # The name alone proves nothing: the ruleset must be active and protect exactly that branch. (An `if`, so a
    # refused ruleset never becomes the loop's, and under pipefail the function's, exit status.)
    if gh api "repos/$repository/rulesets/$id" 2>/dev/null | "$python" -I -c '
import json, sys
try:
    data = json.load(sys.stdin)
    include = data["conditions"]["ref_name"]["include"]
except (ValueError, KeyError, TypeError):
    sys.exit(1)
sys.exit(0 if data.get("enforcement") == "active" and data.get("target") == "branch" and include == ["refs/heads/" + sys.argv[1]] else 1)
' "$name"; then
      echo "$name"
    fi
  done
}

choose() {  # choose BRANCH...: the production branch the maintainer picks on the terminal
  local i=0 name choice
  echo "GitHub protects several production branches; take the initial configuration from:" >&2
  for name in "$@"; do i=$((i + 1)); echo "  $i) $name" >&2; done
  read -r -p "Number (1-$#): " choice < /dev/tty || { echo "no choice made" >&2; exit 1; }
  case "$choice" in ''|*[!0-9]*) echo "no valid choice: $choice" >&2; exit 1 ;; esac
  { [ "$choice" -ge 1 ] && [ "$choice" -le $# ]; } || { echo "no valid choice: $choice" >&2; exit 1; }
  shift $((choice - 1))
  printf '%s\n' "$1"
}

# The initial configuration comes from a production branch, since only those are reached by reviewed PRs alone:
# the one GitHub protects as production, the one chosen among several, or --config-branch. Its configuration names
# the config branch, whose own configuration must agree or name another listed production branch whose own
# configuration names itself: a finished change of the config branch is followed once, as the CLI and the dispatcher
# do (tools/factory/branches.py follow). Before settings.py protects any production branch, the remote default
# branch names it.
[ -z "$start" ] || [[ $start =~ $name_pattern ]] || { echo "invalid branch name: $start" >&2; exit 1; }
production="$(protected_branches | tr '\n' ' ')"
set -- $production  # validated names only, no glob characters
if [ -n "$start" ]; then
  [ $# -eq 0 ] || [[ " $production" == *" $start "* ]] \
    || { echo "$start is not protected as a production branch on GitHub; choose one of: ${production% }" >&2; exit 1; }
elif [ $# -eq 1 ]; then
  start="$1"
elif [ $# -gt 1 ]; then
  [ -t 0 ] || { echo "GitHub protects several production branches (${production% }): choose one with --config-branch NAME" >&2; exit 1; }
  start="$(choose "$@")"
else
  start="$(safe_git ls-remote --symref "$url" HEAD | awk '$1 == "ref:" && $3 == "HEAD" { sub("^refs/heads/", "", $2); print $2 }')"
  [[ $start =~ $name_pattern ]] || { echo "cannot read the default branch of $repository" >&2; exit 1; }
  echo "note: GitHub protects no production branch yet (or gh cannot read its rulesets); the default branch $start names the config branch" >&2
fi
fetch_branch "$repo" "$start"
start_config="$(config_of "$start")"
named="$(named_by "$start" "$start_config")"
[[ $named =~ $name_pattern ]] || { echo "$start names no valid config branch" >&2; exit 1; }
fetch_branch "$repo" "$named" "the config branch that $start names is not on GitHub; $not_yet"
named_config="$(config_of "$named")"
target="$(named_by "$named" "$named_config")"
[[ $target =~ $name_pattern ]] || { echo "the config branch $named names no valid config branch" >&2; exit 1; }
target_config=""
if [ "$target" != "$named" ]; then
  fetch_branch "$repo" "$target" "the config branch that $named names is not on GitHub yet; finish that change first"
  target_config="$(config_of "$target")"
  named_by "$target" "$target_config" >/dev/null
fi
[ -z "$branch" ] || [[ $branch =~ $name_pattern ]] || { echo "invalid branch name: $branch" >&2; exit 1; }
config_branch="$("$python" -I -c '
import json, sys
first, name, branch, repository, hint = json.loads(sys.argv[1]), sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6]
def names(config, label, *levels):
    try:
        return [entry["name"] for level in levels for entry in config["branches"][level]]
    except (KeyError, TypeError):
        sys.exit(f"factory/config.json on {label} has no valid branch list (branches): {hint}")
target, config = first["config_branch"], first
if target != name:
    production = names(first, name, "production")
    if target not in production:
        sys.exit(f"the config branch {name} names {target}, which it does not list as a production branch; finish that change first")
    config = json.loads(sys.argv[2])
    if config["config_branch"] != target:
        sys.exit(f"the config branch {name} names {target}, whose own configuration does not name itself; finish that change first")
    name = target
if first.get("repository") != repository or config.get("repository") != repository:
    sys.exit(f"factory/config.json on {name} names another repository")
listed = names(config, name, "validation", "production")
if (branch or name) not in listed:
    sys.exit(f"{branch or name} is not listed in factory/config.json on {name}; choose a listed branch with --branch")
print(name)
' "$named_config" "$target_config" "$named" "$branch" "$repository" "$not_yet")"
[[ $config_branch =~ $name_pattern ]] || { echo "cannot read the config branch of $repository" >&2; exit 1; }
[ "$config_branch" = "$named" ] || echo "note: $named names the config branch $config_branch; following it" >&2
[ -z "$production" ] || [[ " $production" == *" $config_branch "* ]] \
  || { echo "the config branch $config_branch is not protected as a production branch on GitHub (${production% }); refusing" >&2; exit 1; }
branch="${branch:-$config_branch}"

# Only the reviewed installer of the config branch may continue.
expected="$(git -C "$repo" rev-parse --verify --quiet "refs/remotes/origin/$config_branch:$self")" \
  || { echo "origin/$config_branch has no $self yet" >&2; exit 1; }
actual="$(git -C "$repo" hash-object --no-filters "$here/install-factory-cli.sh")"
[ "$expected" = "$actual" ] \
  || { echo "this installer differs from origin/$config_branch; run the copy of an up-to-date $config_branch checkout" >&2; exit 1; }

if [ ! -e "$control" ]; then
  safe_git clone --quiet --branch "$branch" "$url" "$control"
else
  # Stage 2 must come from the current control branch: switch and fast-forward a clean existing control checkout.
  fetch_branch "$control" "$branch"
  tip="$(git -C "$control" rev-parse "refs/remotes/origin/$branch")"
  current="$(git -C "$control" symbolic-ref --quiet --short HEAD || true)"
  local_tip="$(git -C "$control" rev-parse --verify --quiet "refs/heads/$branch" || true)"
  if [ -n "$(safe_git -C "$control" status --porcelain --ignored)" ] \
      || { [ -n "$local_tip" ] && ! git -C "$control" merge-base --is-ancestor "$local_tip" "$tip"; }; then
    echo "control checkout $control is not a clean clone of $branch; fix it or choose another --control-dir" >&2
    exit 1
  fi
  if [ "$current" != "$branch" ]; then
    if [ -n "$local_tip" ]; then
      safe_git -C "$control" switch --quiet "$branch"
    else
      safe_git -C "$control" switch --quiet --no-track -c "$branch" "$tip"
    fi
  fi
  [ "$(git -C "$control" rev-parse HEAD)" = "$tip" ] || safe_git -C "$control" merge --ff-only --quiet "$tip"
fi
exec "$python" -I -S -B "$control/tools/factory/cli/factory.py" _install \
  --control-dir "$control" --candidate-dir "$candidate" --bin-dir "$bin" --branch "$branch" $keys
