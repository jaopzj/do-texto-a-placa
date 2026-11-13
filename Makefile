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

.PHONY: imagem versao shell configurar pcb rotear drc

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
