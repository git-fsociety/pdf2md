#!/usr/bin/env bash
# Instala o pdf2md: cria um venv isolado e um atalho em ~/.local/bin/pdf2md
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"

python3 -m venv "${DIR}/.venv"
"${DIR}/.venv/bin/pip" install --quiet --upgrade pip
"${DIR}/.venv/bin/pip" install --quiet -r "${DIR}/requirements.txt"

mkdir -p "${BIN_DIR}"
cat > "${BIN_DIR}/pdf2md" <<WRAP
#!/usr/bin/env bash
exec "${DIR}/.venv/bin/python" -I "${DIR}/pdf2md.py" "\$@"
WRAP
chmod 755 "${BIN_DIR}/pdf2md"

echo "pdf2md instalado em ${BIN_DIR}/pdf2md"
case ":${PATH}:" in *":${BIN_DIR}:"*) ;; *) echo "adicione ${BIN_DIR} ao PATH";; esac
