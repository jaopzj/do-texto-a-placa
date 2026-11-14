# ADR-014: Claude Haiku 5.5 no agente e andamento no terminal

Status: aceito · Data: 2026-11-14

## Contexto

A primeira execução do eval (Opus 5.5, esforço `high`) bateu com o gabarito, mas custou
US$ 0,34: cerca de 60% em tokens de saída, quase todos de raciocínio. O john pediu para usar
o Claude Haiku 5.5 e para ver no terminal o que o agente está fazendo, porque o
`make eval` só mostrava uma linha por execução, no fim, e o `python -m src.agente`
despejava cada resultado inteiro (só a leitura do ESP32 tem quase 9 mil caracteres).

O Haiku 5.5 tem duas diferenças que importam aqui: não tem modelo reserva no servidor (um
pedido com `fallbacks` não serve para ele) e cobra em duas faixas de preço, conforme o
tamanho do prompt de cada pedido (até 100 mil tokens e acima disso).

## Decisão

- **Haiku 5.5.** `claude-haiku-5-5` entra na tabela `PRECOS`, com as duas faixas:
  US$ 0,10 / 0,50 por milhão de tokens de entrada e saída até 100 mil tokens de prompt, e
  US$ 0,50 / 2,50 acima disso; leitura do cache a 0,1 vez e gravação a 1,25 vez a entrada.
  A faixa é escolhida pelo prompt inteiro do pedido (entrada comum mais cache). Os modelos
  de `SEM_RESERVA` (hoje só o Haiku) vão sem `fallbacks` e sem o beta correspondente; uma
  recusa do Haiku encerra o laço com o motivo, como já acontecia quando a recusa persistia.
  O padrão não muda: continua o Opus 5.5 com esforço `high` (ADR-011) até uma rodada do eval
  mostrar que outro modelo atinge a meta. O Haiku é escolhido com `MODELO=claude-haiku-5-5`
  no `make eval` ou `--modelo` no `python -m src.agente`.
- **Andamento.** O laço passa a emitir um `Evento` por resposta do modelo e por ferramenta
  executada (`eventos=`), sem mudar o registro completo (`registrar=`), que continua indo
  para o `registro.txt` de cada execução. `src/agente/terminal.py` transforma os eventos em
  poucas linhas: por passo, a hora, a espera, os tokens, o custo do passo e o acumulado e o
  que o modelo pensou (cortado); por ferramenta, `ok` ou `ERRO` com o código e a mensagem.
  O eval mostra também o início de cada execução e as etapas da medida (gerando a netlist,
  comparando com o gabarito). Tudo sai com `flush`, e o `make eval` passa
  `PYTHONUNBUFFERED=1`, para as linhas aparecerem na hora dentro do Docker.
- `python -m src.agente` ganha `--modelo` e `--esforco`, como o eval.

## Consequências

- O custo do Haiku sai certo também quando um pedido passa de 100 mil tokens de prompt.
- Sem modelo reserva, uma recusa do Haiku por segurança conta como execução que não
  terminou. Se isso aparecer no eval, fica registrado no motivo da execução.
- O eval, chamado de outro código sem `avisar`, fica em silêncio; só o `main` imprime.
- Mudar o padrão para o Haiku (ou outro modelo) depende de uma rodada registrada em
  `docs/evals.md` que atinja a meta, e de um novo ADR.
