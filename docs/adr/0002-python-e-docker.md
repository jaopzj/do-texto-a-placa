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
- Java 25 copiado da imagem oficial Temurin, porque o Freerouting exige essa
  versão e não depende do Java da base da imagem (ver nota da troca 21→25 abaixo).
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

## Nota: troca de Java 21 para Java 25 (Marco 1, issue M1-3)

Data: 2026-11-13

Ao subir o Freerouting para a versão 2.2.4, o jar passou a ser compilado para o
bytecode do Java 25. Rodar esse jar com o Java 21 (versão anterior do estágio
`java` no Dockerfile) resulta em `UnsupportedClassVersionError` (class file
version error): a JVM 21 não carrega classes geradas para uma versão de bytecode
mais nova que a dela.

Por isso o estágio `java` do `docker/Dockerfile` passou de `eclipse-temurin:21-jre`
para `eclipse-temurin:25-jre`. Essa é a única mudança necessária: o Java continua
sendo copiado da imagem oficial Temurin para `/opt/java/openjdk`, sem depender do
Java da base do KiCad. Com o Java 25 a JVM carrega `freerouting.jar` sem erro de
versão de classe.
