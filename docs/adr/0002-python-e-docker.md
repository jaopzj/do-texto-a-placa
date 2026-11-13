# ADR-002: Python e Docker, com versões fixadas

Status: aceito · Data: 2026-11-13

## Contexto

O projeto depende de várias ferramentas ao mesmo tempo (KiCad, Freerouting, Python
e suas bibliotecas), cada uma numa versão específica. O time usa Windows e Linux.
Sem um ambiente padronizado, cada máquina se comporta de um jeito.

## Decisão

- Linguagem: Python, porque o ecossistema do KiCad e do SKiDL é Python.
- Ambiente: um container Docker definido em `docker/Dockerfile`, partindo da imagem
  oficial do KiCad com a versão 10 fixada pela tag exata (nunca `latest`).
- Java 21 copiado da imagem oficial Temurin, porque o Freerouting atual exige essa
  versão e não depende do Java da base da imagem.
- Freerouting com a versão fixada no Dockerfile.
- No Windows, o projeto roda dentro do WSL2.
- O container roda com o usuário de quem o executa, para os arquivos gerados não
  ficarem com dono root.

## Consequências

- Qualquer pessoa reproduz o ambiente com `make imagem`.
- A imagem é grande, e o primeiro build demora.
- Atualizar qualquer versão é uma decisão consciente: muda o Dockerfile e ganha um
  novo ADR.
- O KiCad instalado no Windows, usado só para visualizar, deve estar na mesma versão
  do container.
