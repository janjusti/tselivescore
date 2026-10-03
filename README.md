# TSELiveScore

Feito na base da pressa extrema. [XGH é vida](https://gohorseprocess.com.br/extreme-go-horse-xgh/).

Acompanha a apuração das Eleições 2026 consumindo os arquivos JWS do TSE.

## Como executar

### Docker (recomendado)

```bash
docker compose build
docker compose run --rm tselivescore br
```

Para acompanhar o governo de um estado:

```bash
docker compose run --rm tselivescore sp
```

Opções adicionais:

```bash
docker compose run --rm tselivescore br --wait 3 --printables 10
```

### Sem Docker

```bash
pip install -r src/reqs/requirements-base.txt
cd src
python tselivescore.py br
```

### Devcontainer (opcional)

No VS Code ou Cursor, instale a extensão [Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers), abra a pasta no container e execute:

```bash
cd src
python tselivescore.py br
```

## Cargos suportados

| Argumento | Cargo       | Código eleição TSE |
|-----------|-------------|--------------------|
| `br`      | Presidência | 6257               |
| `<uf>`    | Governador  | 6259               |

## Rate limit do TSE

O TSE documenta um limite de [100 requisições por segundo por IP](https://www.tse.jus.br/eleicoes/informacoes-tecnicas-sobre-a-divulgacao-de-resultados). Com `--wait 5` (padrão), cada janela faz 0,2 req/s — dezenas de janelas no mesmo IP ficam bem abaixo do teto.
