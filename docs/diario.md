# Diário de bordo

## 2026-11-12
- Criei o repositório e a estrutura de pastas.
- Próximo passo: quadro de tarefas no GitHub.

## 2026-11-13 — Marco 1 fechado (spike da netlist à placa)
- M1-1: netlist `teste.net` fixada como fonte única de verdade + `valida_netlist.sh`.
- M1-3: Freerouting 2.2.4 rodando no Java 25 (Dockerfile + nota no ADR-002).
- M1-2: netlist → `.kicad_pcb` via `kinet2pcb` (Caminho A); 3 footprints, DRC ok.
- M1-4: round-trip DSN → Freerouting → SES headless; placa roteada com 7 trilhas.
- M1-5: ADR-003 (`pcbnew` como exceção temporária ao ADR-001).
- M1-6: relatório do spike em `docs/spikes/netlist-ate-placa.md`.
- Reproduzível por `make pcb` + `make rotear`. Orquestração via time de agentes
  (Planejador, Desenvolvedor, Pesquisador); docs finais consolidados pelo Orquestrador.

## 2026-11-13 — Marco 2, Parte 1 (bibliotecas do container, issue #12)
- Fiz: `.home/` como HOME do container (ignorada pelo Git), variáveis de bibliotecas no `Makefile` e o alvo `make configurar`; os 3 avisos `lib_footprint_issues` do DRC da placa de teste sumiram.
- Aprendi: o SKiDL 3.0.0 (ferramenta `kicad10`) lê `KICAD10_SYMBOL_DIR`, e não `KICAD_SYMBOL_DIR`; as tabelas do KiCad 10 usam `${KICAD10_FOOTPRINT_DIR}` e `${KICAD10_SYMBOL_DIR}`, que o kicad-cli resolve sozinho, mas o SKiDL não.
- Travou: o SKiDL 3.0.0 acha a `fp-lib-table`, mas não indexa nenhuma biblioteca dela, porque compara o tipo `"KiCad"` com as aspas. Não afeta a netlist (o footprint vai como texto), mas a busca de footprints do SKiDL não funciona. Rever na Parte 4.

## 2026-11-13 — Marco 2, Parte 4 (netlist em SKiDL)
- Fiz: `placas/monitor-umidade/circuito.py` com as tabelas da Parte 3 (conectores, ligações e não usados) por nome de pino, validação que exige cada pino numa rede ou marcado como não usado, `make netlist`, `make testes` e 11 testes; ERC do SKiDL sem erros nem avisos, e o `kinet2pcb` monta a placa com os 6 footprints.
- Aprendi: com um `Circuit` próprio e `tag` fixa por peça, a netlist sai igual a cada execução (exceto a data); os pinos não usados vão para a rede `NC` do SKiDL, então qualquer pino esquecido vira aviso de ERC.
- Travou: nada no código. Ficam pendências físicas do `pecas.md`: a lista de verificação da seção 4 está toda em aberto (VIN com 5 V pelo USB, ordem dos pinos de LCD, sensor e conversor), a distância de 25,4 mm entre as fileiras do ESP32 foi estimada a olho, o lado do pino 1 de cada conector fêmea precisa ser marcado na Parte 5, e não há fotos em `fotos/`.

## 2026-11-13 — Marco 2, Partes 5 e 6 (placa-modelo e posicionamento manual)
- Fiz: versionei a placa-modelo (contorno 100 × 100 mm, trilha e espaçamento 0,2 mm); `scripts/gerar_placa.py` copia os footprints da netlist para a placa-modelo, `posicoes.yaml` + `scripts/aplicar_posicoes.py` posicionam as 6 peças e `scripts/verificar_placa.py` confere referências, footprints, redes, posições, contorno e sobreposição; `make posicionar` termina com DRC de 0 violações e as 14 ligações do ratsnest; ADR-004 estende a exceção do `pcbnew`.
- Aprendi: o KiCad ordena os footprints pelo UUID ao salvar, então UUIDs aleatórios mudam o arquivo a cada execução; com UUIDs derivados da referência a placa sai idêntica byte a byte. O `.kicad_pro` do modelo vai junto ao salvar, e é ele que leva as regras para o DRC.
- Travou: faltam dados físicos. A distância entre as fileiras do conversor e qual lado fica à esquerda não estão no `pecas.md` (J5 e J6 estão em posição provisória), os corpos dos módulos não têm medidas (não dá para conferir colisão entre módulos encaixados) e os mínimos da fábrica não foram anotados (Parte 5, passo 1).

## 2026-11-13 — Marco 2, Partes 7 e 8 (roteamento, saídas e `make placa`)
- Fiz: `make placa` roda tudo, da netlist aos arquivos da fábrica, e para no primeiro erro; o Freerouting roteou as 8 redes (44 trilhas, 1 via) e o DRC da placa roteada deu 0 violações e 0 pendências; Gerbers de 7 camadas, furação, posições e BOM (`scripts/bom.py`) em `saida/fabrica/`, conferidos por `scripts/verificar_saidas.py`; `gabarito.net` e ADR-005 (módulos como conectores fêmea); 33 testes.
- Aprendi: `kicad-cli pcb drc --exit-code-violations` também falha com ligações pendentes, então serve de portão do pipeline; o Freerouting deu o mesmo roteamento em execuções seguidas, mas os UUIDs das trilhas importadas do SES são aleatórios, então a placa roteada só é igual na geometria, e não byte a byte; o script do spike contava vias com `"(via "` e dizia 0 vias, porque o KiCad 10 grava `(via` com quebra de linha.
- Travou: nada no pipeline. Continuam as pendências físicas das Partes 2, 5 e 6 (fileiras do conversor, corpos dos módulos, mínimos da fábrica, verificações da seção 4 do `pecas.md`) e a conferência visual da placa no KiCad, que é de uma pessoa.

## 2026-11-13 — Marco 2 concluído
- Fiz: o john conferiu a placa roteada no KiCad e no visualizador 3D, e o PR #13 entrou na `main` (Partes 1 a 8, com o `gabarito.net` e os ADRs 004 e 005). O M2 está concluído.
- Aprendi: o repositório ainda não tem GitHub Actions; os testes só rodam com `make testes` dentro do container.
- Travou: nada. Próximo marco: M3 (base de componentes v0).

## 2026-11-14 — Marco 3, Partes 4 e 5 (carregador da base e GitHub Actions)
- Fiz: versionei o modelo e o YAML do sensor de umidade (Partes 2 e 3); `src/componentes/carregar.py` lê e valida a base e, com qualquer problema, levanta `ErroBase` com arquivo e campo; o modelo ficou estrito (ADR-006); `src/componentes/kicad.py` confere símbolo e footprint nas bibliotecas do container; `tests/test_componentes.py` com 94 testes; `.github/workflows/testes.yml` roda a base a cada push e pull request. `make testes` no container: 127 passaram.
- Aprendi: sem `extra="forbid"` o Pydantic ignora um campo com erro de digitação, e o PyYAML aceita chave repetida ficando com o último valor; os dois aceitariam dado errado em silêncio. A checagem do guia (apagar `status`) funciona: o erro diz `sensor-umidade-capacitivo.yaml: status: Field required`.
- Travou: o YAML do sensor descreve o sensor capacitivo de 3 pinos (GND, VCC, AOUT), mas o `pecas.md`, o `circuito.py` e o `gabarito.net` usam o sensor resistivo FC-28 de 4 pinos (A0, D0, GND, VCC); falta decidir qual é a peça da placa antes da Parte 6. As fontes do sensor citam o datasheet sem página.

## 2026-11-14 — Marco 3, Parte 6 (base completa e circuito.py lendo a base)
- Fiz: o modelo ganhou `conectores` (ADR-007); versionei o ESP32 DevKitC V4 (38 pinos), o LCD e o conversor, que estavam só na pasta local; corrigi o ESP32 (duas fileiras 1x19, GPIO8/GPIO9 pela página 5 da Espressif), o LV4 do conversor e passei todos os módulos para barra macho (ADR-008); o `circuito.py` busca símbolo, footprint e pinos na base; `pecas.md`, `gabarito.net` e testes refeitos para o ESP32 de 38 pinos e o sensor HW-101.
- Aprendi: os 19 pinos por fileira do ESP32 fazem a serigrafia de J1/J2 encostar na referência de J3/J4, e o DRC acusa `silk_overlap`; J3 e J4 foram 3 mm para a direita.
- Travou: a distância entre as fileiras do ESP32 (25,4 mm) e entre os lados do conversor continuam estimadas; ESP32 e LCD ainda estão em `rascunho`, e alguns rótulos de função do ESP32 não estão na página 5 da Espressif.

## 2026-11-14 — Marco 4, Parte 2 (especificação da placa)
- Fiz: `src/especificacao.py` com o modelo da especificação (projeto, módulos, alimentação e restrições, cada decisão com `decidido_por`) e `ler_especificacao()`, que valida e confere os ids contra a base (ADR-009); `placas/monitor-umidade/spec.yaml` escrito à mão; `tests/test_especificacao.py`, que também roda no GitHub Actions.
- Aprendi: a proposta (página 9) previa barra fêmea e montagem por encaixe, mas o ADR-008 trocou para barra macho; a especificação segue a decisão mais nova.
- Travou: quem decidiu o LCD e as duas camadas segue a proposta (agente), e falta o john confirmar; os valores mínimos de trilha, espaçamento e furo da fábrica não estão anotados no `pecas.md`, então ficaram fora das restrições.

## 2026-11-14 — Marco 4, Parte 3 (ferramentas do agente)
- Fiz: `src/agente/ferramentas.py` com as seis ferramentas lendo a base de verdade, resultado sempre em dicionário com `ok`, erro com código e próximo passo, e estado que só muda em chamada válida (ADR-010); `tests/test_ferramentas.py`, sem chamar o modelo, também no GitHub Actions.
- Aprendi: os ids da base usam hífen, então a busca precisa ignorar hífens além de espaços e sublinhados, ou "sensor umidade" (o termo que falhou no protótipo) não acha nada. A fonte de uma decisão só é verificável se apontar para algo que o código confere: componente, regra, pino ou decisão da especificação.
- Travou: o `agente_minimo.py` do protótipo não está no repositório nem na pasta local, então o laço do agente ainda não existe; não há ferramenta para desfazer uma ligação errada.
