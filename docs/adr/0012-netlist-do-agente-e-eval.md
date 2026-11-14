# ADR-012: Netlist a partir do estado do agente e eval de equivalência

Status: aceito · Data: 2026-11-14

## Contexto

As Partes 4 e 5 do Marco 4 fecham o ciclo entre o agente e o KiCad. A Parte 4 pede
`src/gerar_netlist.py`, que monta o circuito em SKiDL a partir das peças e ligações que as
ferramentas registraram (ADR-010), "do mesmo jeito que o `circuito.py` faz à mão". A Parte 5
pede `src/evals/comparar.py`, que diz se duas netlists são o mesmo circuito comparando
grupos de pinos ligados, com cada pino identificado pela peça e pelo nome ("lcd: SDA").

O estado do agente e o gabarito não usam as mesmas referências. O agente dá uma referência
por peça (`U1` para o ESP32) e liga pinos pelo número da peça (1 a 38). O `circuito.py` e o
`gabarito.net` têm um conector por fileira (`J1` e `J2` para o ESP32, ADR-007), e a netlist
só guarda o número do pino dentro do conector (1 a 19). O nome do pino não está na netlist:
os símbolos `Conn_01xNN` chamam todos de `Pin_N`.

Três pontos ficaram em aberto no guia:

- algumas peças têm nomes repetidos (três GND no ESP32, dois no conversor), e "esp32: GND"
  não diz qual deles;
- a netlist não diz que peça da base é cada conector, a não ser pelo campo `value`;
- um pino sozinho numa rede, ou uma rede de um pino só, não é uma ligação.

## Decisão

**Gerador (`src/gerar_netlist.py`).** `planejar(estado, base)` confere o estado de novo
contra a base, sem confiar nas ferramentas: peça que não está na base, referência repetida,
pino inexistente, nome que não bate com o número, pino `nao_usado` ligado, pino em duas
redes, rede com espaço e rede com menos de dois pinos levantam `ErroGeracao` com todos os
problemas, e nenhum arquivo é escrito. Depois:

- cada peça abre nos conectores da base (`conectores_fisicos()`), com símbolo, footprint e
  ordem dos pinos da base, como no `circuito.py`;
- as referências são J1, J2... na ordem em que o agente selecionou as peças e, dentro de
  cada peça, na ordem dos conectores na base. O `value` é o id da peça, mais o nome do
  conector quando a peça tem vários (`"esp32-devkitc-v4 J2"`), como no `circuito.py`;
- os pinos que o agente não ligou vão para a rede NC do SKiDL, como a tabela `NAO_USADOS`, e
  voltam no `Plano` (`sem_ligacao_por_peca`), para não sumirem em silêncio.

`montar_circuito` e `gerar_netlist` usam o SKiDL; `planejar` não, e roda no GitHub Actions.

**Eval (`src/evals/comparar.py`).** `ler_estrutura` lê a netlist KiCad (S-expression, versão
"D") com um leitor próprio, sem o SKiDL, para o eval não depender do gerador que ele avalia.
Cada componente é reconhecido pelo `value` e conferido contra a base: o id e o conector
precisam existir, e o símbolo, o footprint e a quantidade de pinos precisam ser os do
conector na base. A posição do pino no conector vira o número e o nome do pino na peça.

- Um pino é `"<id da peça>: <nome>"`, e `"<id da peça>: <nome>#<número>"` quando o nome se
  repete na peça (`"esp32-devkitc-v4: GND#14"`). Assim os três GND do ESP32 contam como três
  pinos, e ligar só dois deles é diferente de ligar os três.
- Um componente é `"<id>"` ou `"<id>/<conector>"`. Uma peça sem nenhuma ligação também conta:
  sobrar ou faltar um componente torna as netlists diferentes.
- Cada rede com dois pinos ou mais vira um grupo. Uma rede de um pino só (como as
  `unconnected-(...)` que o KiCad escreve) é pino sem ligação: fica fora dos grupos, em
  `isolados`.
- Duas netlists são equivalentes quando os conjuntos de componentes e de grupos são iguais.
  Nome de rede, referência, ordem, data, tstamps e a linha do SKiDL não entram.
- `comparar` devolve uma `Comparacao` com os componentes e grupos que faltam ou sobram, e,
  para cada pino que mudou, com quem ele estava ligado no esperado e no obtido.

O que não dá para ler sem adivinhar é erro (`ErroNetlist`), com todos os problemas: arquivo
malformado, componente sem `value` ou que não confere com a base, nó de componente que não
existe, pino que o conector não tem, pino em duas redes, referência repetida e duas unidades
da mesma peça.

## Consequências

- A checagem da Parte 4 está em `tests/test_gerar_netlist.py`: as ligações do `circuito.py`,
  escritas à mão por peça (`U1`, `LCD1`, `S1`, `U2`), passam pelas ferramentas reais, viram
  netlist e saem equivalentes ao `gabarito.net` e à netlist do próprio `circuito.py`. Uma
  ligação trocada, esquecida ou um GND a menos saem diferentes, com os pinos apontados.
- O `gabarito.net` e o `circuito.py` não mudaram.
- As referências do agente não batem uma a uma com as do gabarito: o conversor sai com HV em
  J5 e LV em J6, e o gabarito tem o contrário. O eval não liga para isso, mas o
  `posicoes.yaml` é escrito por referência. Na Parte 7, para a netlist do agente passar pelo
  `make placa`, as posições vão precisar ser achadas por peça e conector, não por J1...J6.
- Duas unidades da mesma peça (dois sensores) não são comparáveis ainda: seria preciso
  descobrir qual unidade de um lado corresponde a qual do outro. O eval recusa com erro em
  vez de adivinhar. Quando uma placa precisar disso, a comparação muda com outro ADR.
- O reconhecimento da peça depende do `value` que o `circuito.py` e o `gerar_netlist.py`
  escrevem. Uma netlist feita no editor de esquemático do KiCad, com outro `value`, é
  recusada, e não comparada pela metade.
- `tests/test_comparar.py` e a parte sem SKiDL de `tests/test_gerar_netlist.py` rodam no
  GitHub Actions; os testes que geram netlist rodam no `make testes`.
