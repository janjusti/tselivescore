# TSELiveScore

Feito na base da pressa extrema. [XGH é vida](https://gohorseprocess.com.br/extreme-go-horse-xgh/).

## Como executar

Primeiro, dá aquele clone maneiro no repo. Depois, no seu terminal...

### Sem devcontainer
```bash
cd .devcontainer
docker compose -f docker-compose.yml up
```
Depois, para cada apuração que desejar, execute:
```bash
docker exec -it tselivescore bash -c "python /temp/src/tselivescore.py br"
```
Pode substituir "br" pela sigla do estado a verificar (e.g. sp).

---

### Com devcontainer
No VSCode, instale a extensão [Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers). 

Depois, aperte F1 e vá para a opção "Dev Containers: Open Folder in Container...".

Escolha a pasta do repo clonado.

Vá para o bash via VSCode e insira:
```bash
cd src
python tselivescore.py br
```