# Atalhos do projeto. Rode "make <alvo>" a partir da raiz do repositório.
# Atenção: as linhas de comando abaixo começam com TAB, não com espaços.

IMAGEM := do-texto-a-placa

# Variáveis de ambiente do container (Marco 2 / Parte 1):
# - HOME aponta para .home/ (dentro do repositório, ignorada pelo Git), para a configuração
#   do KiCad criada pelo "make configurar" não sumir entre um comando e outro.
# - KICAD_SYMBOL_DIR, KICAD10_SYMBOL_DIR e KICAD10_FOOTPRINT_DIR dizem onde estão as
#   bibliotecas do KiCad. O SKiDL 3 (ferramenta kicad10) lê KICAD10_SYMBOL_DIR, e as tabelas
#   copiadas pelo "make configurar" usam ${KICAD10_FOOTPRINT_DIR} e ${KICAD10_SYMBOL_DIR}.
AMBIENTE := -e HOME=/projeto/.home \
    -e KICAD_SYMBOL_DIR=/usr/share/kicad/symbols \
    -e KICAD10_SYMBOL_DIR=/usr/share/kicad/symbols \
    -e KICAD10_FOOTPRINT_DIR=/usr/share/kicad/footprints

# Roda um comando dentro do container, com o seu usuário e a pasta do projeto montada
RUN := docker run --rm --user $(shell id -u):$(shell id -g) $(AMBIENTE) -v "$(CURDIR)":/projeto -w /projeto $(IMAGEM)

# Netlist de entrada do "make pcb" (fonte única de verdade, fixada na M1-1)
NETLIST ?= placas/teste/teste/teste.net
# Placa gerada pelo "make pcb" e verificada pelo "make drc"
# (dá para trocar: make drc PLACA=outra.kicad_pcb)
PLACA ?= placas/teste/teste/teste.kicad_pcb
# Placa roteada gerada pelo "make rotear" (round-trip Freerouting). Marco 1 / M1-4.
PLACA_ROTEADA ?= placas/teste/teste/teste_roteada.kicad_pcb

.PHONY: imagem versao shell configurar netlist posicionar placa testes eval briefing regras custos correcao pcb rotear drc

imagem:
	docker build -t $(IMAGEM) docker/

versao:
	$(RUN) kicad-cli version
	$(RUN) java -version
	$(RUN) python -c "import skidl, pydantic, yaml; print('Bibliotecas Python: ok')"
	$(RUN) ls /opt/freerouting

shell:
	docker run --rm -it --user $(shell id -u):$(shell id -g) $(AMBIENTE) -v "$(CURDIR)":/projeto -w /projeto $(IMAGEM) bash

# Copia as tabelas-modelo de bibliotecas (footprints e símbolos) que vêm com o KiCad
# para a pasta de configuração em .home/. Basta rodar uma vez. Marco 2 / Parte 1.
configurar:
	mkdir -p .home/.config/kicad/10.0
	$(RUN) cp /usr/share/kicad/template/fp-lib-table .home/.config/kicad/10.0/
	$(RUN) cp /usr/share/kicad/template/sym-lib-table .home/.config/kicad/10.0/

# Gera a netlist da placa de referência a partir do circuito em SKiDL. Marco 2 / Parte 4.
netlist:
	$(RUN) python placas/monitor-umidade/circuito.py

# Placa de referência: netlist + placa-modelo -> placa com as peças nas posições do YAML,
# conferida contra a netlist e o YAML e passada pelo DRC. Marco 2 / Parte 6.
MONITOR := placas/monitor-umidade
PLACA_MONITOR := saida/monitor-umidade/monitor-umidade.kicad_pcb
posicionar:
	$(RUN) python scripts/gerar_placa.py -n $(MONITOR)/monitor-umidade.net -m $(MONITOR)/modelo/modelo.kicad_pcb -o $(PLACA_MONITOR)
	$(RUN) python scripts/aplicar_posicoes.py $(PLACA_MONITOR) $(MONITOR)/posicoes.yaml $(PLACA_MONITOR)
	$(RUN) python scripts/verificar_placa.py $(PLACA_MONITOR) $(MONITOR)/monitor-umidade.net $(MONITOR)/posicoes.yaml
	$(RUN) kicad-cli pcb drc --severity-all -o saida/monitor-umidade/drc.rpt $(PLACA_MONITOR)
	@echo "Placa posicionada em $(PLACA_MONITOR); DRC em saida/monitor-umidade/drc.rpt"

# Pipeline completo da placa de referência (Marco 2 / Partes 7 e 8):
# netlist -> placa posicionada -> roteamento -> DRC -> arquivos da fábrica.
# Apaga as saídas anteriores antes de começar, para nada ficar desatualizado, e para no
# primeiro passo que falhar. As entradas feitas à mão (pecas.md, a placa-modelo e o
# posicoes.yaml) ficam no Git; ver a seção "Pipeline" do README.
PLACA_ROTEADA_MONITOR := saida/monitor-umidade/monitor-umidade_roteada.kicad_pcb
FABRICA := saida/fabrica
CAMADAS_FABRICA := F.Cu,B.Cu,F.Mask,B.Mask,F.Silkscreen,B.Silkscreen,Edge.Cuts
placa:
	rm -rf saida/monitor-umidade $(FABRICA)
	$(MAKE) netlist
	$(MAKE) posicionar
	$(RUN) python scripts/spike/round_trip_freerouting.py -i $(PLACA_MONITOR) -o $(PLACA_ROTEADA_MONITOR)
	$(RUN) python scripts/verificar_placa.py $(PLACA_ROTEADA_MONITOR) $(MONITOR)/monitor-umidade.net $(MONITOR)/posicoes.yaml
	$(RUN) kicad-cli pcb drc --severity-all --exit-code-violations -o saida/monitor-umidade/drc_roteada.rpt $(PLACA_ROTEADA_MONITOR)
	$(RUN) kicad-cli pcb drc --severity-all --exit-code-violations --format json -o saida/monitor-umidade/drc_roteada.json $(PLACA_ROTEADA_MONITOR)
	mkdir -p $(FABRICA)
	$(RUN) kicad-cli pcb export gerbers --layers $(CAMADAS_FABRICA) -o $(FABRICA)/ $(PLACA_ROTEADA_MONITOR)
	$(RUN) kicad-cli pcb export drill -o $(FABRICA)/ $(PLACA_ROTEADA_MONITOR)
	$(RUN) kicad-cli pcb export pos --format csv --units mm -o $(FABRICA)/posicoes.csv $(PLACA_ROTEADA_MONITOR)
	$(RUN) python scripts/bom.py $(MONITOR)/monitor-umidade.net $(FABRICA)/bom.csv
	$(RUN) python scripts/verificar_saidas.py $(PLACA_ROTEADA_MONITOR) $(MONITOR)/monitor-umidade.net $(MONITOR)/posicoes.yaml saida/monitor-umidade/drc_roteada.json $(FABRICA)
	@echo "Placa roteada em $(PLACA_ROTEADA_MONITOR); arquivos da fábrica em $(FABRICA)/"

# Roda os testes automáticos (pytest) dentro do container.
testes:
	$(RUN) python -m pytest tests/

# Eval do gabarito (Marco 4, Parte 6): roda o agente N vezes sobre o spec.yaml, compara
# cada netlist com o gabarito.net e acrescenta a rodada a docs/evals.md. Chama a API da
# Anthropic (custa dinheiro): a chave vem da variável ANTHROPIC_API_KEY do seu terminal,
# repassada ao container só neste alvo, e nunca fica em arquivo.
# Ex.: make eval N=5 MODELO=claude-opus-5-5 ESFORCO=medium OBS="primeira rodada"
N ?= 5
MODELO ?= claude-haiku-5-5
ESFORCO ?= high
OBS ?=
eval:
	@test -n "$$ANTHROPIC_API_KEY" || { echo "Defina ANTHROPIC_API_KEY no terminal antes do make eval."; exit 1; }
	docker run --rm --user $(shell id -u):$(shell id -g) $(AMBIENTE) -e ANTHROPIC_API_KEY -e PYTHONUNBUFFERED=1 -v "$(CURDIR)":/projeto -w /projeto $(IMAGEM) python -m src.evals.rodar --n $(N) --modelo $(MODELO) --esforco $(ESFORCO) --observacao "$(OBS)" --registrar

# Briefing (Marco 5, Partes 1 e 2): o agente transforma o pedido em português na
# especificação da placa, com no máximo seis perguntas e a primeira aprovação (responda s ou
# escreva uma correção). É interativo (docker -it). Chama a API da Anthropic, com a chave da
# variável ANTHROPIC_API_KEY do seu terminal, como no make eval. A especificação aprovada vai
# para saida/briefing/<projeto>/spec.yaml.
# Ex.: make briefing PEDIDO="quero um monitor de umidade do solo com ESP32 e um LCD"
PEDIDO ?=
briefing:
	@test -n "$$ANTHROPIC_API_KEY" || { echo "Defina ANTHROPIC_API_KEY no terminal antes do make briefing."; exit 1; }
	docker run --rm -it --user $(shell id -u):$(shell id -g) $(AMBIENTE) -e ANTHROPIC_API_KEY -e PYTHONUNBUFFERED=1 -v "$(CURDIR)":/projeto -w /projeto $(IMAGEM) python -m src.briefing "$(PEDIDO)" --modelo $(MODELO) --esforco $(ESFORCO)

# Motor de regras (Marco 5, Parte 3; ADR-017): confere um circuito (o estado do agente, em
# JSON) contra as regras da base. Não chama a API. Sai com 0 se aprovado, 1 se reprovado.
# Ex.: make regras ESTADO=tests/dados/regras/sensor-no-adc2.json
ESTADO ?= tests/dados/regras/referencia.json
SPEC ?= placas/monitor-umidade/spec.yaml
regras:
	$(RUN) python -m src.regras $(ESTADO) --spec $(SPEC)

# Registro de custos (ADR-017): resumo por etapa e total do projeto, de saida/custos/.
# Ex.: make custos PROJETO=monitor-umidade DETALHE=--detalhe
PROJETO ?= monitor-umidade
DETALHE ?=
custos:
	$(RUN) python -m src.custos $(PROJETO) $(DETALHE)

# Laço de correção (Marco 5, Parte 4; ADR-018): o agente monta o circuito, o código confere
# netlist, regras e o DRC da placa roteada, e devolve os problemas ao agente (até 3
# correções). Se não resolver, para e explica. Chama a API da Anthropic, como o make eval.
# Ex.: make correcao  (ou SPEC=saida/briefing/<projeto>/spec.yaml)
correcao:
	@test -n "$$ANTHROPIC_API_KEY" || { echo "Defina ANTHROPIC_API_KEY no terminal antes do make correcao."; exit 1; }
	docker run --rm --user $(shell id -u):$(shell id -g) $(AMBIENTE) -e ANTHROPIC_API_KEY -e PYTHONUNBUFFERED=1 -v "$(CURDIR)":/projeto -w /projeto $(IMAGEM) python -m src.correcao $(SPEC) --modelo $(MODELO) --esforco $(ESFORCO)

# Gera a placa a partir da netlist (Caminho A: kinet2pcb). Marco 1 / M1-2.
pcb:
	$(RUN) python scripts/spike/netlist_para_pcb.py -i $(NETLIST) -o $(PLACA)
	@echo "Placa gerada em $(PLACA)"

# Roteia a placa no Freerouting (headless): DSN -> SES -> placa com trilhas.
# Marco 1 / M1-4. Depende de "make pcb" ter gerado a placa de entrada.
rotear:
	$(RUN) python scripts/spike/round_trip_freerouting.py -i $(PLACA) -o $(PLACA_ROTEADA)
	@echo "Placa roteada em $(PLACA_ROTEADA)"

drc:
	mkdir -p saida
	$(RUN) kicad-cli pcb drc -o saida/drc.rpt $(PLACA)
	@echo "Relatório do DRC em saida/drc.rpt"
