# ADR-010: Contrato das ferramentas do agente

Status: aceito · Data: 2026-11-14

## Contexto

A Parte 3 do Marco 4 pede seis ferramentas reais para o agente, que consultam a base de
componentes: `buscar_componente`, `ler_dados_componente`, `selecionar_componente`,
`conectar`, `registrar_decisao` (com fonte obrigatória) e `registrar_pendencia`. O guia
manda trazer o `agente_minimo.py` do protótipo para `src/agente/`, mas esse arquivo não está
no repositório nem na pasta local do john; só o trecho do laço aparece na proposta
(página 10).

O teste 2 do protótipo (proposta, páginas 11 e 12) mostrou o risco: sem o conversor na
biblioteca, o agente registrou "use um conversor" sem procurar a peça, e nada avisou que ela
não existia. A lição da proposta é que uma regra no prompt é um pedido, e uma regra no código
é uma garantia.

O guia deixa alguns comportamentos em aberto: o que conta como "fonte", como identificar um
pino quando a peça tem vários com o mesmo nome (os três GND do ESP32) e se a busca deve
ignorar hífens, que são o separador dos ids da base.

## Decisão

As ferramentas ficam em `src/agente/ferramentas.py`, na classe `Ferramentas`, que guarda o
estado do projeto (seleções, ligações, decisões e pendências) e lê a base só por
`carregar_todos()`. O laço do agente e o adaptador do provedor de IA ficam para as partes
seguintes; este módulo não chama nenhum modelo.

Contrato comum:

- toda ferramenta devolve um dicionário: `{"ok": True, ...}` no sucesso e, na recusa,
  `{"ok": False, "erro", "mensagem", "proximo_passo"}`, às vezes com dados para o agente se
  corrigir (as peças selecionadas, os pinos da peça, os formatos de fonte). Recusa não
  levanta exceção;
- os argumentos são validados por modelos Pydantic estritos, como a base (ADR-006):
  argumento desconhecido, faltando, de tipo errado ou texto vazio é `entrada_invalida`;
- uma chamada recusada não muda o estado: tudo é conferido antes de qualquer gravação.
  As tentativas de selecionar um id que não existe são contadas à parte
  (`tentativas_inexistentes`), porque o eval da Parte 6 mede esse número; elas não fazem
  parte do estado do projeto;
- `executar_ferramenta(nome, entrada)` recebe o pedido como o modelo envia e devolve o
  mesmo tipo de resultado, também para ferramenta desconhecida.

Regras de cada ferramenta:

- **buscar_componente**: compara o termo com o id e a descrição sem maiúsculas, acentos,
  espaços, sublinhados, hífens e pontuação. Os hífens entram porque são o separador dos
  ids, e sem eles "sensor umidade" (o termo que falhou no protótipo) não acharia
  `sensor-umidade-capacitivo`. Um componente aparece se o termo sem separadores está dentro
  do id sem separadores, ou se cada palavra do termo é o começo de uma palavra do id ou da
  descrição. Todos os achados voltam, em ordem de id; a ferramenta nunca escolhe um.
- **ler_dados_componente**: devolve os campos que estão no YAML e só eles
  (`model_dump(exclude_unset=True)`), sem preencher nada que falte.
- **selecionar_componente**: aceita só o id exato da base. Id inexistente volta com
  sugestões da busca e com a orientação de registrar uma pendência. A referência (`U1`,
  `LCD1`...) começa por letra, só tem letras, dígitos e `_`, e não pode repetir no projeto,
  sem diferença entre maiúsculas e minúsculas. O mesmo componente pode ser selecionado com
  duas referências. Componente em `rascunho` é aceito, com um aviso no resultado.
- **conectar**: a referência precisa estar selecionada. O pino é o número (inteiro) ou o
  nome exato da base. Um nome que aparece em vários pinos da peça liga todos eles, como o
  `circuito.py` faz. Pino marcado `nao_usado` na base é recusado. Um pino fica numa rede só:
  ligar de novo na mesma rede não muda nada, e ligar em outra rede é recusado. O nome da
  rede não tem espaços.
- **registrar_decisao**: `decisao`, `motivo` e `fonte` são obrigatórios. A fonte (um texto
  ou uma lista) precisa apontar para algo que o código consegue conferir:
  `componente:<id>`, `componente:<id>/regra:<id da regra>`,
  `componente:<id>/pino:<nome ou número>` ou, quando a sessão recebeu uma especificação,
  `especificacao:<caminho da decisão>` (ex.: `modulos.3`). Qualquer fonte que não confere
  recusa a decisão inteira. Texto livre, como "datasheet do ESP32", é recusado, porque
  ninguém consegue conferir: o que não está na base vira pendência.
- **registrar_pendencia**: `necessidade` e `motivo` obrigatórios. A mesma necessidade
  (comparada sem maiúsculas, acentos e separadores) não é registrada duas vezes.

## Consequências

- Sem a peça na base, nenhuma ferramenta a coloca no projeto, e o caminho que sobra ao
  agente é a pendência, que o eval da Parte 7 vai cobrar.
- Uma decisão só fica registrada com uma fonte que existe na base ou na especificação.
  A proposta previa guardar decisões sem fonte como "suposições do agente"; aqui elas são
  recusadas, como o john pediu.
- Não há ferramenta para desfazer uma seleção ou uma ligação. Um erro do agente só se
  corrige numa nova execução. Se isso atrapalhar os evals, uma ferramenta nova entra com
  outro ADR.
- `estado()` entrega seleções, ligações e redes para o gerador de netlist da Parte 4. As
  referências do agente (`U1`...) são por peça, e o gerador é que vai abrir cada peça nos
  seus conectores (J1, J2...), como a tabela `PECAS` do `circuito.py`.
- `tests/test_ferramentas.py` só precisa do Pydantic e do PyYAML e roda no GitHub Actions.
