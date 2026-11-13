#!/usr/bin/env bash
#
# valida_netlist.sh - Valida a netlist KiCad usada como fixture do spike (M1-1).
#
# Roda HEADLESS (sem GUI) e pode ser executado dentro do container Docker:
#   docker run --rm -v "$PWD":/projeto -w /projeto do-texto-a-placa \
#       bash scripts/spike/valida_netlist.sh [caminho-da-netlist]
#
# Verificacoes:
#   1. O arquivo existe e nao esta vazio.
#   2. Tem formato de netlist KiCad (comeca com "(export" e possui a secao "(components").
#   3. Possui >= 2 componentes (blocos "(comp").
#   4. Cada componente declara um footprint nao vazio.
#
# Saida:
#   0   -> netlist valida.
#   !=0 -> arquivo ausente/incompleto, com mensagem clara em stderr.
#
set -euo pipefail

NETLIST="${1:-placas/teste/teste/teste.net}"
MIN_COMPONENTES=2

erro() {
    echo "ERRO: $*" >&2
    exit 1
}

# 1. Existencia e conteudo -------------------------------------------------
if [[ ! -f "$NETLIST" ]]; then
    erro "arquivo de netlist nao encontrado: '$NETLIST'"
fi
if [[ ! -s "$NETLIST" ]]; then
    erro "arquivo de netlist esta vazio: '$NETLIST'"
fi

# 2. Formato KiCad ---------------------------------------------------------
if ! grep -q '(export' "$NETLIST"; then
    erro "'$NETLIST' nao parece ser uma netlist KiCad (secao '(export' ausente)"
fi
if ! grep -q '(components' "$NETLIST"; then
    erro "'$NETLIST' nao contem a secao '(components'"
fi

# 3. Contagem de componentes ----------------------------------------------
# Cada componente e um bloco "(comp" com "(ref ...". Contamos as refs dentro
# de (components. Usamos awk para delimitar a secao de componentes e evitar
# contar refs que aparecem em (nets) ou (libparts).
NUM_COMP=$(awk '
    { sub(/\r$/, "") }
    /\(components/ { dentro=1 }
    dentro && /\(groups/ { dentro=0 }
    dentro && /\(comp([ (]|$)/ { n++ }
    END { print n+0 }
' "$NETLIST")

if (( NUM_COMP < MIN_COMPONENTES )); then
    erro "netlist incompleta: encontrados $NUM_COMP componente(s), esperado >= $MIN_COMPONENTES"
fi

# 4. Footprint por componente ---------------------------------------------
# Para cada componente dentro de (components, exige um (footprint "...") nao vazio.
FALTANDO=$(awk '
    { sub(/\r$/, "") }
    /\(components/ { dentro=1 }
    dentro && /\(groups/ { dentro=0 }
    dentro && /\(comp([ (]|$)/ {
        if (ref != "" && !tem_fp) { faltando = faltando ref " "; }
        ref = ""; tem_fp = 0;
        comp_aberto = 1;
    }
    dentro && comp_aberto && match($0, /\(ref "[^"]+"/) {
        if (ref == "") { ref = substr($0, RSTART+6, RLENGTH-7); }
    }
    dentro && comp_aberto && match($0, /\(footprint "[^"]+"/) { tem_fp = 1; }
    END {
        if (ref != "" && !tem_fp) { faltando = faltando ref " "; }
        print faltando;
    }
' "$NETLIST")

if [[ -n "${FALTANDO// /}" ]]; then
    erro "componente(s) sem footprint: ${FALTANDO}"
fi

echo "OK: netlist valida -> '$NETLIST' ($NUM_COMP componentes, todos com footprint)"
exit 0
