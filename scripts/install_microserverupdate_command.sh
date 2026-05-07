#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="$HOME/.local/bin"
PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'

mkdir -p "$TARGET_DIR"

install_wrapper() {
  local command_name="$1"
  local target_path="$TARGET_DIR/$command_name"
  cat >"$target_path" <<EOF
#!/usr/bin/env bash
exec bash "$REPO_ROOT/scripts/$command_name" "\$@"
EOF
  chmod +x "$target_path"
  printf '[install-microserverupdate] Installed wrapper at %s\n' "$target_path"
}

install_wrapper microserverupdate
install_wrapper microserverfeed

for rc_file in "$HOME/.bashrc" "$HOME/.profile" "$HOME/.zshrc"; do
  if [ ! -f "$rc_file" ]; then
    touch "$rc_file"
  fi
  if ! grep -Fqx "$PATH_LINE" "$rc_file"; then
    printf '\n%s\n' "$PATH_LINE" >> "$rc_file"
  fi
done

printf '[install-microserverupdate] Run: source ~/.bashrc\n'
printf '[install-microserverupdate] Then run: microserverupdate or microserverfeed\n'
