# Atalhos do projeto. Rode "make <alvo>" a partir da raiz do repositório.
# Atenção: as linhas de comando abaixo começam com TAB, não com espaços.

IMAGEM := do-texto-a-placa

# Roda um comando dentro do container, com o seu usuário e a pasta do projeto montada
RUN := docker run --rm --user $(shell id -u):$(shell id -g) -e HOME=/tmp -v "$(CURDIR)":/projeto -w /projeto $(IMAGEM)

# Placa usada pelo "make drc" (dá para trocar: make drc PLACA=outra.kicad_pcb)
PLACA ?= placas/teste/teste.kicad_pcb

.PHONY: imagem versao shell drc

imagem:
	docker build -t $(IMAGEM) docker/

versao:
	$(RUN) kicad-cli version
	$(RUN) java -version
	$(RUN) python -c "import skidl, pydantic, yaml; print('Bibliotecas Python: ok')"
	$(RUN) ls /opt/freerouting

shell:
	docker run --rm -it --user $(shell id -u):$(shell id -g) -e HOME=/tmp -v "$(CURDIR)":/projeto -w /projeto $(IMAGEM) bash

drc:
	mkdir -p saida
	$(RUN) kicad-cli pcb drc -o saida/drc.rpt $(PLACA)
	@echo "Relatório do DRC em saida/drc.rpt"
