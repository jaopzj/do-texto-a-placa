# Do texto à placa

Plataforma de projeto de placas de circuito impresso conduzida por um agente de IA:
o usuário descreve o hardware em português e o agente entrega a placa pronta para
fabricação, usando o KiCad e verificações reais. A IA propõe, o código decide.

Status: em estruturação (Marco 2).

## Requisitos

- Windows com WSL2 (Ubuntu) ou Linux
- Docker Desktop, com a integração WSL ativada para o Ubuntu
- `make` e `git` instalados no Ubuntu

## Como rodar

```bash
make imagem      # constrói a imagem Docker (a primeira vez demora)
make configurar  # copia as tabelas de bibliotecas do KiCad para .home/ (uma vez só)
make versao      # confere KiCad, Java, Python e Freerouting dentro do container
make drc         # roda o DRC na placa de teste e salva o relatório em saida/
make netlist     # gera a netlist da placa de referência (SKiDL)
make testes      # roda os testes automáticos (pytest)
make shell       # abre um terminal dentro do container
```

O container usa como pasta pessoal (`HOME`) a pasta `.home/` do repositório, ignorada
pelo Git. É lá que o `make configurar` guarda a configuração do KiCad, para ela não
sumir entre um comando e outro. Se apagar a `.home/`, rode `make configurar` de novo.

## Estrutura

- `docker/`: Dockerfile e dependências Python
- `docs/adr/`: decisões de arquitetura registradas
- `docs/diario.md`: diário de bordo
- `componentes/`: base de componentes
- `placas/`: placas do projeto (a de referência é `monitor-umidade`)
- `src/`: código da plataforma
- `tests/`: testes automáticos
