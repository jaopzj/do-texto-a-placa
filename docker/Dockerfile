# Ambiente do projeto "Do texto à placa"
#
# Versões fixadas de propósito. Para mudar alguma, altere aqui
# e registre a mudança num novo ADR.

# TROQUE pela tag exata do KiCad 10 que você escolheu no Docker Hub
# (página kicad/kicad, aba Tags). Ex.: 10.0.3-full. Nunca use "latest".
ARG KICAD_TAG=10.0.8-full

# Estágio 1: só serve para pegar o Java 21, que o Freerouting atual exige.
FROM eclipse-temurin:21-jre AS java

# Estágio 2: a imagem do projeto, partindo da imagem oficial do KiCad.
FROM kicad/kicad:${KICAD_TAG}

ARG FREEROUTING_VERSION=2.2.4

# Para instalar pacotes precisamos ser root. Na hora de rodar, o Makefile
# usa o seu usuário, para os arquivos gerados não ficarem com dono root.
USER root

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3-venv python3-pip ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Java 21 copiado do estágio 1
COPY --from=java /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk


# Ambiente Python isolado. "--system-site-packages" mantém acesso ao módulo
# pcbnew que vem com o KiCad (vamos precisar dele no Marco 1).
RUN python3 -m venv --system-site-packages /opt/venv
ENV PATH="/opt/venv/bin:/opt/java/openjdk/bin:${PATH}"

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Freerouting, baixado direto da página de releases do projeto
ADD https://github.com/freerouting/freerouting/releases/download/v${FREEROUTING_VERSION}/freerouting-${FREEROUTING_VERSION}.jar /opt/freerouting/freerouting.jar
RUN chmod 644 /opt/freerouting/freerouting.jar

WORKDIR /projeto
