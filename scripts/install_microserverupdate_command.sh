#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="$HOME/.local/bin"
TARGET_PATH="$TARGET_DIR/microserverupdate"
PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'

mkdir -p "$TARGET_DIR"
cat >"$TARGET_PATH" <<EOF
#!/usr/bin/env bash
exec bash "$REPO_ROOT/scripts/microserverupdate" "\$@"
EOF
chmod +x "$TARGET_PATH"

for rc_file in "$HOME/.bashrc" "$HOME/.profile" "$HOME/.zshrc"; do
  if [ ! -f "$rc_file" ]; then
    touch "$rc_file"
  fi
  if ! grep -Fqx "$PATH_LINE" "$rc_file"; then
    printf '\n%s\n' "$PATH_LINE" >> "$rc_file"
  fi
done

printf '[install-microserverupdate] Installed wrapper at %s\n' "$TARGET_PATH"
printf '[install-microserverupdate] Run: source ~/.bashrc\n'
printf '[install-microserverupdate] Then run: microserverupdate\n'
