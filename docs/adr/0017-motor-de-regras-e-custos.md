# ADR-017: Motor de regras e registro de custos

Status: aceito · Data: 2026-11-16

## Contexto

A Parte 3 do Marco 5 pede o motor de regras: um módulo que lê as regras técnicas da base de
componentes e confere se o circuito do agente as cumpre. As regras são código, não sugestões.
O agente pode ler os resultados, mas não pode alterar, ignorar, desligar ou contornar as
regras, e isso tem de valer pela arquitetura, não pelo prompt. Quando falta um dado, o motor
diz que não deu para verificar. Ele nunca presume que o circuito está certo.

O john pediu, junto, o registro dos custos de execução: tokens, modelo, chamadas, custo de
cada uma e acumulado, por etapa e no total do projeto. O registro separa o que é conhecido
do que é estimado, sem inventar valores, e também anota as operações que não chamam o
modelo.

O laço de correção com o DRC (Parte 4) fica fora desta decisão.

## Decisão

**Uma função por regra, numa tabela só de leitura.** `src/regras.py` tem `REGRAS`, um
`MappingProxyType` que liga cada regra da base (id do componente e id da regra) a uma de duas
coisas:

- uma função determinística, que recebe o circuito e devolve os problemas;
- o motivo de a regra não ser conferível pelas ligações. São quatro: `i2c-address`,
  `lcd-display-format`, `i2c-pullups` e `level-shifter-supply-order`, que tratam de firmware,
  operação ou de olhar a peça. Elas saem como `manual`.

Uma regra que está na base e não está na tabela sai como `nao_verificavel` e, se for de
`erro`, reprova o circuito. Um teste confere que as duas listas são iguais.

Cada regra tem uma de quatro situações:

- `ok`;
- `violada`, com componente, referência, pinos, redes, explicação e correção;
- `nao_verificavel`, com o dado que faltou;
- `manual`.

O circuito é aprovado quando nenhuma regra de `erro` está violada ou não verificável. Uma
regra de `aviso` (por exemplo `gpio-strapping`) aparece no relatório, mas não reprova.

**Separação pela arquitetura.** O motor recebe só `selecoes` e `ligacoes` do estado e
confere tudo de novo com `gerar_netlist.planejar`, a mesma conferência da netlist. Qualquer
outra chave que o agente ponha no estado não muda nada. Ele roda depois do agente (`python
-m src.agente`) ou sozinho (`python -m src.regras`). Nenhuma ferramenta do agente nem do
briefing chama o motor, e os resultados são `dataclass(frozen=True)`. `verificar` não tem
parâmetro para pular regra, e a tabela não aceita escrita. Testes cobrem cada um desses
pontos.

**Tensões vindas só da base.**

- A tensão de uma rede de alimentação vem do `tensao_max` dos pinos de alimentação dela.
  Valores diferentes na mesma rede deixam a tensão desconhecida.
- Os lados de um conversor (os pinos de alimentação citados por `referencia`) não contam:
  eles seguem a tensão que recebem.
- A tensão de um pino de sinal vem do `referencia` dele ou, sem isso, do `nivel_logico` da
  peça.
- O limite de um pino é o `tensao_max` dele.
- Os números GPIO de `gpio-input-only`, `gpio-flash-reserved` e `gpio-strapping` foram
  copiados do texto das próprias regras na base, e um teste confere que batem.

**Três mudanças de dados, todas com fonte.**

- `Pino.referencia` (opcional): o pino de alimentação que define a tensão de um pino de
  sinal. Só pode citar um pino de alimentação da mesma peça. No conversor, HV1 a HV4 passaram
  a citar HV e LV1 a LV4 passaram a citar LV. É o texto que já estava nas funções ("Lado de
  alta/baixa tensão", manual 010-0061, p. 1), agora num campo que o código lê.
- O pino 5V do ESP32 ganhou `tensao_max: 5.0`, como o 3V3 já tinha `3.3`. A base já dizia
  "Alimentação de 5 V" nas funções, com a mesma fonte (esp-dev-kits, p. 5).
- A especificação ganhou `wifi` (opcional, uma decisão como as outras). O john escolheu
  registrar `wifi: true` no `spec.yaml` do monitor, citando a proposta (p. 9). Sem o campo,
  `adc2-wifi` sai não verificável quando há sinal analógico num pino ADC2.

**Custos.** `src/custos.py` tem `Custos`, uma execução com id próprio e uma lista de
`Lancamento`:

- `chamada_llm`: uma resposta do modelo, com modelo, passo, tokens (entrada, saída e cache),
  segundos de espera, custo e custo acumulado;
- `operacao`: uma ferramenta do agente ou o motor de regras, com o tempo que levou e
  `custo: sem_custo`.

O que é medido e o que é calculado fica separado:

- tokens e modelo vêm da API. A `Resposta` do laço ganhou `modelo` e `custo_fonte`;
- o valor em US$ é `calculado` a partir da tabela de preços do adaptador
  (`FONTE_DOS_PRECOS`). Não é o valor cobrado, que só a fatura dá;
- um modelo fora da tabela dá `desconhecido`, sem valor, e o resumo diz `custo_completo:
  false`.

`Custos.ouvinte` vira o `eventos` de `laco.conversar` e repassa os eventos ao terminal. O
evento de ferramenta ganhou o tempo que ela levou. A gravação acrescenta linhas JSON em
`saida/custos/<projeto>.jsonl`, e cada linha é lida de volta campo a campo. Quem grava:

- o briefing (`etapa: briefing`). O projeto só se sabe na aprovação; antes disso vai para
  `sem-projeto.jsonl`. O custo é gravado mesmo num cancelamento ou numa falha da API;
- o agente (`agente`) e o motor depois dele (`motor_de_regras`);
- `python -m src.regras` (`motor_de_regras`).

`python -m src.custos <projeto>` mostra o resumo por etapa e o total, com `--detalhe`,
`--execucao` e `--json`. O eval continua com a medição própria (ADR-013).

## Consequências

- O circuito de referência sai **reprovado**: 11 ok, 4 manuais e uma regra de `erro` não
  verificável (`gpio-not-5v-tolerant`). A base não diz a tensão da saída AOUT do sensor
  HW-101, que vai no IO34. Com esse dado (com fonte), o mesmo circuito passa: há um teste
  com uma base de teste para isso. O motor não presume que a saída está abaixo de 3,3 V.
- A base também não diz a tensão dos pull-ups do adaptador I2C do LCD. Por isso um LCD ligado
  direto no ESP32, sem conversor, sai não verificável (e reprovado), não aprovado.
- `gpio-input-only` só pega o caso que dá para ver pelas ligações: um GPIO só de entrada numa
  rede em que todos os outros pinos também são entradas. Uma saída de firmware não aparece
  nas ligações.
- O relatório (`Relatorio.para_dict`) é o formato que a Parte 4 vai devolver ao agente no
  laço de correção. Nada desta decisão faz esse laço.
- Um componente novo com regras precisa das funções dele em `REGRAS`. Até lá, as regras
  dele saem não verificáveis.
