# TSELiveScore

Feito na base da pressa extrema. [XGH é vida](https://gohorseprocess.com.br/extreme-go-horse-xgh/).

Acompanha a apuração das Eleições 2026 consumindo os arquivos JWS do TSE — via dashboard web ou CLI.

## Dashboard (recomendado)

```bash
docker compose up --build                              # desenvolvimento local (padrão; hot reload)
docker compose --profile prod up --build tselivescore-prod  # produção (imagem fixa, sem porta exposta)
```

Abra [http://localhost:8080](http://localhost:8080).

- Adicione quantos painéis quiser: Presidência, governadores, deputados federais e estaduais (distritais no DF)
- Configure candidatos visíveis por painel
- Refresh no TSE configurável (padrão: 5s, mínimo 5s)
- Polling ao TSE só ocorre com navegadores abertos (sessão ativa); ao fechar a aba, para em ~30s
- Cada navegador tem painéis independentes (`localStorage`); o backend faz a união dos painéis de sessões ativas para poll, mas cada um vê só os seus
- Layout salvo no navegador (`localStorage`)

O backend faz **uma requisição por painel** a cada ciclo — 10 painéis com refresh de 5s = 2 req/s, bem abaixo do [limite de 100 req/s por IP](https://www.tse.jus.br/eleicoes/informacoes-tecnicas-sobre-a-divulgacao-de-resultados) documentado pelo TSE.

## CLI

```bash
docker compose run --rm --entrypoint python tselivescore src/tselivescore.py br
docker compose run --rm --entrypoint python tselivescore src/tselivescore.py sp --wait 3 --printables 10
```

### Sem Docker

```bash
pip install -r src/reqs/requirements-base.txt
cd src
python webapp.py          # dashboard em :8080
python tselivescore.py br # CLI
```

### Devcontainer (opcional)

No VS Code ou Cursor, instale a extensão [Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers), abra a pasta no container e execute `python src/webapp.py`.

## Cargos suportados

| Painel (web) | CLI (`<uf>`) | Cargo              | Eleição TSE |
|--------------|--------------|--------------------|-------------|
| `br:1`       | `br`         | Presidência        | 6257        |
| `<uf>:3`     | `<uf>`       | Governador         | 6259        |
| `<uf>:5`     | —            | Senador            | 6259        |
| `<uf>:6`     | —            | Deputado Federal   | 6259        |
| `<uf>:7`     | —            | Deputado Estadual  | 6259        |
| `df:7`       | —            | Deputado Distrital | 6259        |
