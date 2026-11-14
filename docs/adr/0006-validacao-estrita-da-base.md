# ADR-006: Validação estrita da base de componentes

Status: aceito · Data: 2026-11-14

## Contexto

O guia do MVP (Marco 3, Partes 2 e 4) define o modelo Pydantic da base de componentes e
um carregador que lê cada YAML e o passa ao modelo. Do jeito mínimo do guia, alguns erros
passariam sem aviso e virariam dado errado para o agente, contra o princípio "nada vem da
memória do modelo" (a base é a única fonte):

- o Pydantic ignora campos desconhecidos, então `tensao_maxima: 3.6` (erro de digitação de
  `tensao_max`) sumiria sem aviso;
- o Pydantic converte tipos por conta própria: o texto `"3.3"` vira número e `true` vira 1;
- o PyYAML aceita a mesma chave duas vezes no arquivo e fica só com o último valor;
- dois arquivos com o mesmo `id` fariam um substituir o outro no dicionário;
- um arquivo `.yml` não seria lido, e ninguém perceberia;
- texto vazio, tensão zero ou negativa, alimentação mínima maior que a máxima, componente
  sem pinos ou dois pinos com o mesmo número passariam como válidos.

## Decisão

O modelo (`src/componentes/modelo.py`) mantém os campos e os tipos do guia e acrescenta:

- `extra="forbid"` e `strict=True` em todas as classes: campo desconhecido é erro e nenhum
  tipo é convertido (um inteiro continua valendo onde se espera tensão, porque 5 V é 5,0 V);
- texto obrigatório com pelo menos um caractere que não seja espaço;
- `kicad_simbolo` e `kicad_footprint` no formato `Biblioteca:Nome`;
- tensões maiores que zero, `pagina` e `numero` a partir de 1;
- pelo menos um pino; número de pino e id de regra sem repetição dentro do componente;
- `alimentacao_min` menor ou igual a `alimentacao_max`.

Nomes de pino podem repetir, porque módulos reais têm vários pinos GND.

O carregador (`src/componentes/carregar.py`) recusa chave repetida no YAML, conteúdo que
não é um mapa, arquivo fora de UTF-8, arquivo `.yml` e `id` repetido entre arquivos. Ele
junta os problemas de todos os arquivos e levanta um único `ErroBase`, que diz o arquivo e
o campo de cada um. Se houver qualquer problema, nenhum componente é devolvido.

A existência do símbolo e do footprint nas bibliotecas do KiCad é conferida por
`src/componentes/kicad.py`, que só lê as pastas das bibliotecas. Esse teste roda dentro do
container (`make testes`) e é pulado, com o motivo escrito, onde as bibliotecas não existem
(o GitHub Actions).

Ficam de fora, por enquanto:

- exigir `pagina` quando a fonte é um datasheet. O CLAUDE.md pede a página, mas o modelo do
  guia a deixa opcional e o YAML do sensor ainda não a traz; a regra entra quando os
  componentes tiverem as páginas;
- exigir que o nome do arquivo seja igual ao `id` e conferir `nivel_logico` contra a
  alimentação, que não estão definidos na documentação.

## Consequências

- Um YAML com erro faz `make testes` e o GitHub Actions falharem, com a mensagem apontando
  o arquivo e o campo.
- Escrever um componente exige atenção ao tipo: `"3.3"` entre aspas é recusado.
- Mudar o formato da base passa por este modelo e pelos testes de `tests/test_componentes.py`.
