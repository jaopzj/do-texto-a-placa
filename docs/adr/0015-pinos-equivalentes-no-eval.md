# ADR-015: Pinos equivalentes no eval do gabarito

Status: aceito · Data: 2026-11-15

## Contexto

A primeira rodada do eval com o Claude Haiku 5.5 (2026-11-15, N=5, prompt 1) deu 0 de 5.
O erro foi o mesmo nas cinco execuções, e foi um só: o agente ligou a saída AOUT do sensor
no IO32 do ESP32, e o `gabarito.net` usa o IO34. O resto da netlist bateu nas cinco.

O `spec.yaml`, que é a entrada do agente, só pede "a saída AOUT do sensor vai num pino do
ESP32 com função ADC1" (requisito ligado à regra `adc2-wifi`). Na base, o IO32 tem
`ADC1_CH4` e o IO34 tem `ADC1_CH6`: os dois cumprem. A escolha do IO34 existe só no
`pecas.md` e no `circuito.py`, que o agente não lê. A comparação do ADR-012 é exata, então
reprovava uma resposta que a especificação aceita.

Havia duas saídas: fixar o IO34 no `spec.yaml` (o agente deixa de escolher) ou fazer o eval
aceitar qualquer pino que cumpra o requisito. O john escolheu a segunda num cartão de
decisão (2026-11-15).

## Decisão

**Arquivo de equivalências.** Cada placa pode ter `placas/<placa>/equivalencias.yaml`, escrito
à mão e revisado como o gabarito. Cada entrada diz um pino do gabarito (no rótulo do
`comparar`, `"esp32-devkitc-v4: IO34"`), um prefixo de função da base (`ADC1_`) e o
requisito do `spec.yaml` que deixou a escolha aberta, palavra por palavra. O monitor de
umidade tem uma entrada só, a do IO34.

**Quem decide é o código.** `src/evals/equivalencias.py` (`ler_equivalencias`) confere o
arquivo e calcula as alternativas pela base: os outros pinos da mesma peça com alguma
função que começa pelo prefixo. Para o IO34, são VP, VN, IO35, IO32 e IO33. Requisito que
não está no spec, peça ou pino que a base não tem, pino do gabarito sem a função, pino
repetido ou campo desconhecido levantam `ErroEquivalencias`, e o eval para antes de chamar
a API. Ninguém escreve a lista de pinos à mão.

**Troca na comparação.** `comparar(..., equivalencias=...)` troca, no obtido, o pino
alternativo pelo pino do gabarito antes de comparar, mas só quando: o pino do gabarito está
ligado no gabarito e não aparece no obtido, e exatamente um alternativo aparece no obtido
sem aparecer no gabarito. Em qualquer outro caso (dois alternativos, o pino do gabarito
mais um alternativo, um pino fora do ADC1) nada é trocado e a diferença aparece como antes.
A troca não esconde outro erro: o resto da netlist continua comparado exatamente. A troca
feita fica em `Comparacao.trocas` e no resumo ("troca aceita: ... no lugar de ...").

**Onde vale.** `src/evals/rodar.py` lê `placas/monitor-umidade/equivalencias.yaml` por padrão
(`--equivalencias` troca o arquivo). Sem o argumento, ou com o arquivo ausente, `comparar`
continua exato, como no ADR-012. O `python -m src.evals.comparar` da linha de comando
continua exato.

## Consequências

- O `gabarito.net` não mudou, nem as regras da base, nem o `spec.yaml`, nem o prompt: a
  versão do prompt continua "1". A rodada de 2026-11-15 fica registrada como 0 de 5, porque
  foi medida pela comparação exata; a próxima rodada já usa as equivalências.
- Uma equivalência nova é uma mudança no que conta como acerto. Ela entra por pull request,
  com o john sabendo, como uma mudança no gabarito.
- Só cobre a troca de um pino por outro da mesma peça. Escolhas abertas de outro tipo (outro
  componente, outro conector) precisariam de outro ADR.
- O motor de regras (M5) ainda não existe. Quando existir, a pergunta "este pino cumpre o
  requisito?" pode passar para ele, e este arquivo pode citar a regra em vez do prefixo.
