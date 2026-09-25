# apply-edits — editor de arquivos determinístico guiado por JSON

Edição mecânica não precisa de LLM. Descreva a operação em JSON uma vez e
aplique com **custo zero de token**, em milissegundos, de forma determinística
e reversível.

> Fluxo híbrido recomendado: o LLM decide **o quê** fazer uma vez e emite este
> JSON; o executor aplica de graça quantas vezes precisar.

## Uso

```bash
node bin/apply-edits.js <edits.json> [opções]
# ou, após npm link / instalação global:
apply-edits <edits.json> [opções]
```

Opções:

| Flag | Efeito |
|---|---|
| `--root <dir>` | Diretório base para caminhos relativos (default: cwd) |
| `--dry-run` | Valida e reporta sem escrever |
| `--json` | Emite o relatório como JSON |
| `-h`, `--help` | Ajuda |

## Formato do arquivo de edits

```json
{
  "version": 1,
  "edits": [
    { "file": "a.ts", "op": "replace", "find": "x", "replace": "y", "count": 1 }
  ]
}
```

`count` aceita um inteiro (nº de ocorrências) ou `"all"`/`0` para todas. Default: todas.

## Operações suportadas

| `op` | Campos | O que faz |
|---|---|---|
| `replace` | `find`, `replace`, `count?` | Substitui texto literal |
| `regex_replace` | `pattern`, `replacement`, `flags?` | Substitui via RegExp (flags default `g`) |
| `create` | `content`, `overwrite?` | Cria arquivo (e dirs); recusa sobrescrever sem `overwrite: true` |
| `append` | `content` | Concatena no fim (cria se não existir) |
| `prepend` | `content` | Concatena no início (cria se não existir) |
| `insert_after` | `anchor`, `content` | Insere logo após a primeira ocorrência de `anchor` |
| `insert_before` | `anchor`, `content` | Insere logo antes da primeira ocorrência de `anchor` |
| `delete_file` | `ignoreMissing?` | Remove arquivo; erra se ausente, salvo `ignoreMissing: true` |

## Garantias

- **Transacional**: todas as operações são validadas contra o conteúdo atual
  **antes** de qualquer escrita. Se uma operação for inválida (anchor não
  encontrado, `find` ausente, padrão sem match), nada é escrito e o processo
  sai com código `2`.
- **Encadeamento no lote**: várias edições no mesmo arquivo compõem em ordem
  (ex.: `create` → `append` → `replace`).
- **Sandbox de caminho**: caminhos absolutos ou que escapam de `--root` são
  rejeitados.

## Exemplo

Ver [`apply-edits.example.json`](apply-edits.example.json).

```bash
node bin/apply-edits.js docs/apply-edits.example.json --root . --dry-run
```

## Por que isto é mais barato que LLM

| | JSON determinístico | LLM editando |
|---|---|---|
| Custo | ~zero (CPU local) | tokens de input + output |
| Velocidade | milissegundos | segundos+ |
| Determinismo | sim | não |
| Reversível/testável | sim | parcial |

Use token só quando precisa de **julgamento**. Para o resto, descreva em JSON.
