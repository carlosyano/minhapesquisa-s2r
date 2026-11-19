#!/usr/bin/env bash
# Instala as ferramentas de análise na versão fixada em config.json (ferramentas_maquina).
# Por que fixar: a máquina é quem decide se o código passou; uma ferramenta atualizada sem
# aviso mudaria essa decisão. As versões são as mesmas do ci.yml do repositório.
set -euo pipefail
CFG=".spec2run/config.json"
v() { python3 -P -c "import json,sys;print(json.load(open('$CFG'))['ferramentas_maquina'][sys.argv[1]])" "$1"; }
SEMGREP=$(v semgrep)
# O gitleaks roda pela imagem Docker com a versão escrita no comando SEGREDOS (igual ao ci.yml).
case "$SEMGREP" in *"<VALIDAR"*) echo "preencha ferramentas_maquina em $CFG" >&2; exit 2;; esac
python3 -m pip install --quiet "semgrep==$SEMGREP"
semgrep --version
