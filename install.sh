#!/bin/bash
# Ubuntu/Debian, including proot. Never upgrade the system.
set -euo pipefail
umask 077
BASE=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$BASE"
trap 'printf "%s\n" "[install=failed] Installation stopped. Existing config/data preserved." >&2' ERR
if [[ ! -r /etc/os-release ]]; then
  echo '[install=failed] Supported platforms: Debian/Ubuntu Linux.' >&2; exit 2
fi
. /etc/os-release
case " ${ID:-} ${ID_LIKE:-} " in
  *debian*|*ubuntu*) ;;
  *) echo '[install=failed] Supported platforms: Debian/Ubuntu Linux.' >&2; exit 2 ;;
esac
need=()
if ! command -v python3 >/dev/null 2>&1; then
  need+=(python3 python3-venv ca-certificates)
elif ! python3 -c 'import venv, ssl' >/dev/null 2>&1; then
  need+=(python3-venv ca-certificates)
fi
if [[ ! -f /etc/ssl/certs/ca-certificates.crt ]]; then need+=(ca-certificates); fi
if ((${#need[@]})); then
  elevated=()
  if [[ $(id -u) != 0 ]]; then
    if command -v sudo >/dev/null && sudo -n true 2>/dev/null; then elevated=(sudo -n)
    else
      printf '[install=failed] Missing packages. Ask administrator to install: apt-get install --no-install-recommends'
      printf ' %q' "${need[@]}"; printf '\n'; exit 2
    fi
  fi
  before=$(dpkg-query -W -f='${Package}=${Version}\n' coreutils gnu-coreutils rust-coreutils 2>/dev/null || true)
  "${elevated[@]}" env DEBIAN_FRONTEND=noninteractive apt-get update -qq
  plan=$("${elevated[@]}" env LC_ALL=C apt-get -s install --no-install-recommends --no-upgrade "${need[@]}")
  if grep -Eq '^(Inst|Remv) (coreutils|gnu-coreutils|rust-coreutils)([ :]|$)' <<< "$plan"; then
    echo '[install=failed] Refusing package transaction affecting coreutils.' >&2; exit 2
  fi
  "${elevated[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends --no-upgrade "${need[@]}"
  after=$(dpkg-query -W -f='${Package}=${Version}\n' coreutils gnu-coreutils rust-coreutils 2>/dev/null || true)
  [[ "$before" == "$after" ]] || { echo '[install=failed] coreutils version changed unexpectedly.' >&2; exit 2; }
fi
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python >=3.10 required"'
# Acquire exclusive lifecycle lock in system Python, then invoke internal phase once.
if [[ ${BATCHCODE_INSTALL_LOCKED:-} != 1 ]]; then
  exec python3 "$BASE/src/lifecycle_install.py" "$@"
fi
# No pip or third-party dependencies. --without-pip avoids unnecessary downloads.
if [[ -L .venv ]]; then echo '[install=failed] .venv may not be a symlink.' >&2; exit 2; fi
if [[ ! -x .venv/bin/python ]] || ! .venv/bin/python -c 'import sys,ssl,fcntl; assert sys.version_info >= (3,10)' >/dev/null 2>&1 || [[ ! -f .venv/.install-path ]] || [[ $(cat .venv/.install-path) != "$BASE" ]]; then
  python3 -m venv --without-pip --clear .venv
  printf '%s' "$BASE" > .venv/.install-path
fi
mkdir -p startup locks
if [[ ! -e startup/selection.json ]]; then cp startup/selection.default.json startup/selection.json; fi
chmod 700 batchcode
find model websearch -maxdepth 1 -type f \( -name '*.txt' \) -exec chmod 600 {} +
python3 "$BASE/src/config_upgrade.py"
python3 "$BASE/src/lock_cleanup.py"
./batchcode self-check

# --local skips global registration for CI/embedded deployments only.
if [[ ${1:-} != --local ]]; then
  target=""
  for d in /usr/local/bin "$HOME/.local/bin"; do
    case ":$PATH:" in *":$d:"*)
      if [[ -d "$d" && -w "$d" ]]; then target="$d/batchcode"; break; fi ;;
    esac
  done
  if [[ -z "$target" ]]; then
    echo '[install=failed] No writable PATH directory. Add ~/.local/bin to PATH or install with administrator permissions.' >&2
    exit 2
  fi
  existing=$(command -v batchcode || true)
  if [[ -n "$existing" && "$existing" != "$target" ]]; then
    echo "[install=failed] Conflicting command in PATH: $existing" >&2; exit 2
  fi
  if [[ -e "$target" || -L "$target" ]]; then
    if [[ -L "$target" ]] || ! grep -q '^# batchcode-managed-launcher-v1$' "$target"; then
      echo "[install=failed] Refusing to overwrite unmanaged command: $target" >&2; exit 2
    fi
  fi
  tmp=$(mktemp "${target}.tmp.XXXXXX")
  {
    printf '%s\n' '#!/bin/bash' '# batchcode-managed-launcher-v1'
    printf 'exec %q "$@"\n' "$BASE/batchcode"
  } > "$tmp"
  chmod 755 "$tmp"
  mv -f "$tmp" "$target"
  hash -r
  [[ $(command -v batchcode) == "$target" ]]
  batchcode self-check
fi
printf '%s\n' '[install=ready] Fill API keys in model/deepseek-flash.txt and websearch/tavily.txt. See README.md.'
