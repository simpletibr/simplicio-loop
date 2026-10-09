# Login de CLIs de Execução no Usuário do Serviço

**Parte de:** #1467  
**Dependência:** #1434 (usuário não-root `simplicio-loop`)

## Visão Geral

O watcher do simplicio-loop executa como usuário não-root (`simplicio-loop`) e planeja através de várias CLIs de executores:

- `claude` — Claude CLI
- `codex` — Codex (GitHub Copilot)
- `grok` — Grok (xAI)
- `gemini` — Gemini (Google)
- `agy` — Antigravity CLI
- `opencode` — opencode

Para cada uma, o preflight verifica se a CLI está instalada e autenticada sem expor segredos em logs ou comentários. O módulo `simplicio_loop/exec_auth.py` fornece essas verificações.

## Instalação das CLIs

Cada CLI deve ser instalada para todos os usuários (tipicamente em `/usr/local/bin` ou via package manager).

### Claude CLI

```bash
# Via pip (ou poetry/uv)
pip install claude-cli
# ou em desenvolvimento
cd /caminho/para/claude-cli && pip install -e .
```

### Codex / GitHub Copilot CLI

```bash
# Instalação official
git clone https://github.com/github/copilot-cli.git
cd copilot-cli && npm install -g
# ou
brew install github/copilot-cli/copilot-cli
```

### Grok CLI

```bash
# Instalação official (xAI)
npm install -g @xai/grok-cli
# ou pip
pip install grok-cli
```

### Gemini CLI

```bash
# Instalação official (Google)
pip install google-generativeai
# ou
npm install -g @google/gemini-cli
```

## Login no Usuário do Serviço

Após instalar a CLI globalmente, faça login como o usuário `simplicio-loop`. O comando `simplicio-loop watch247 login-check`
imprime, por família, exatamente o comando abaixo (mapa em `simplicio_loop/watcher247/login_check.py`, um teste por família):

| Família | Comando de login | Origem |
|---------|------------------|--------|
| claude | `sudo -u simplicio-loop -H claude auth login` | VERIFICADO (`claude auth --help`); `claude login` não existe |
| codex | `sudo -u simplicio-loop -H codex login` | VERIFICADO (`codex login --help`) |
| grok | `sudo -u simplicio-loop -H grok login` | VERIFICADO (`grok login --help`) |
| agy | `sudo -u simplicio-loop -H agy` | VERIFICADO: `agy --help` não tem subcomando de login; o sign-in roda ao iniciar a CLI interativa |
| opencode | `sudo -u simplicio-loop -H opencode auth login` | VERIFICADO (`opencode auth --help`) |
| gemini | `sudo -u simplicio-loop -H gemini` | BASEADO EM DOC: CLI não instalada no host de referência; não verificado |

### Claude CLI

```bash
# Como root ou com sudo
sudo -u simplicio-loop -H claude auth login
# ou
sudo -u simplicio-loop -H bash -c "claude auth login"
```

**Credenciais armazenadas em:**  
- `~simplicio-loop/.config/claude/auth.json`
- `~simplicio-loop/.cache/claude/auth.token`

**Verificar status:**
```bash
sudo -u simplicio-loop -H claude auth status
```

### Codex CLI

```bash
sudo -u simplicio-loop -H codex login
# ou (GitHub CLI)
sudo -u simplicio-loop -H gh auth login
```

**Credenciais armazenadas em:**
- `~simplicio-loop/.config/codex/auth.json`
- `~simplicio-loop/.codex/auth`

**Verificar status:**
```bash
sudo -u simplicio-loop -H codex login status   # `codex auth` nao existe
```

### Grok CLI

```bash
sudo -u simplicio-loop -H grok login
# ou com variável de ambiente
sudo -u simplicio-loop -H bash -c "GROK_API_KEY=<sua-chave> grok login"
```

**Credenciais armazenadas em:**
- `~simplicio-loop/.config/grok/auth.json`
- `~simplicio-loop/.grok/credentials`

**Verificar status:**
```bash
# grok nao tem subcomando de status (apenas login/logout); o check usa o arquivo ~/.grok/auth.json.
# NAO rode `grok auth status`: seria interpretado como prompt interativo.
ls -l ~simplicio-loop/.grok/auth.json
```

### Gemini CLI

```bash
# BASEADO EM DOC, não verificado (CLI não instalada no host de referência): iniciar a CLI abre o sign-in interativo.
sudo -u simplicio-loop -H gemini
# ou com variável de ambiente
sudo -u simplicio-loop -H bash -c "GOOGLE_API_KEY=<sua-chave> gemini"
```

**Credenciais armazenadas em:**
- `~simplicio-loop/.config/gemini/auth.json`
- `~simplicio-loop/.gemini/credentials`
- `~simplicio-loop/.cache/gemini/auth.token`

**Verificar status:**
```bash
# gemini: subcomando de status nao verificado (CLI nao instalada no host de referencia);
# o check usa apenas os arquivos de credencial.
ls -l ~simplicio-loop/.gemini/credentials
```

### agy (Antigravity CLI)

```bash
# VERIFICADO: `agy --help` não lista subcomando de login; o sign-in OAuth roda na primeira execução interativa.
sudo -u simplicio-loop -H agy
```

Sem subcomando de status: o preflight (`exec_auth`) confere por `stat` (existe, arquivo regular, não vazio, conteúdo nunca lido) o arquivo `~/.gemini/antigravity-cli/antigravity-oauth-token`. VERIFICADO neste host (o arquivo existe após o sign-in); a ausência do arquivo dá `login_missing`.

### opencode

```bash
# VERIFICADO: `opencode auth --help` (alias: `opencode providers login`)
sudo -u simplicio-loop -H opencode auth login

# Listar provedores/credenciais configurados
sudo -u simplicio-loop -H opencode auth list
```

O preflight roda `opencode auth list` (sai com 0 mesmo sem credenciais) e usa só o número da linha final `N credentials`; N > 0 é login ok. O resto da saída (nomes de provedores) é descartado e o `auth.json` nunca é lido. VERIFICADO neste host, inclusive com `auth.json` vazio/`{}` (0 credentials).

## Variáveis de Ambiente (Alternativa)

Se a CLI suporta autenticação via variável de ambiente, configure no arquivo systemd ou no script de inicialização:

```bash
# ~/.simplicio-loop/env
export ANTHROPIC_API_KEY="sk-..."  # para Claude
export GITHUB_TOKEN="ghp_..."      # para Codex/GitHub
export GROK_API_KEY="xai-..."      # para Grok
export GOOGLE_API_KEY="aiz..."     # para Gemini
```

## Verificação no Preflight

O módulo `exec_auth.py` verifica automaticamente no preflight:

```python
from simplicio_loop.exec_auth import check, check_all, check_sync

# Verificação assíncrona única
result = await check("claude")
if result.status == "ok":
    print(f"{result.family} está autenticado")
elif result.status == "login_missing":
    print(f"{result.family} requer login")
elif result.status == "cli_missing":
    print(f"{result.family} não está instalado")

# Verificação assíncrona concorrente
results = await check_all(["claude", "codex", "grok", "gemini"])
for r in results:
    print(f"{r.family}: {r.status}")

# Verificação síncrona (fallback)
result = check_sync("claude")
print(result)  # "ok" ou "login_missing:claude" ou "cli_missing:claude"
```

## Nenhum Segredo em Logs

A verificação **nunca**:
- Imprime ou captura stdout/stderr dos comandos de auth
- Lê o conteúdo dos arquivos de credenciais (apenas verifica existência)
- Armazena tokens em logs ou comentários
- Expõe variáveis de ambiente

O preflight relatará apenas:
```
login_missing:claude
cli_missing:grok
ok  # para codex
```

## Troubleshooting

### "CLI não encontrada em PATH"

```bash
# Verifique se está instalada globalmente
which claude
which codex
which grok
which gemini

# Se não estiver, instale novamente como root
sudo pip install claude-cli
```

### "Autenticação ausente"

```bash
# Faça login novamente como simplicio-loop
sudo -u simplicio-loop -H claude auth login

# Verifique se o arquivo de credencial existe
ls -la ~simplicio-loop/.config/claude/
```

### "Permissão negada"

```bash
# Verifique proprietário e permissões
ls -la ~simplicio-loop/.config/
ls -la ~simplicio-loop/.cache/

# Repare permissões se necessário
sudo chown -R simplicio-loop:simplicio-loop ~simplicio-loop/.config
sudo chmod 700 ~simplicio-loop/.config
```

## Testes

Executar os testes do módulo:

```bash
python -m pytest tests/test_exec_auth.py -v
```

Testes incluem:
- CLI presente e autenticado
- CLI presente sem autenticação
- CLI ausente (não em PATH)
- Verificações concorrentes com `check_all()`
- Nenhum segredo em saída

## Referências

- Epic #1429: Preparação para execução de múltiplas CLIs
- Issue #1434: Usuário não-root para o watcher
- Módulo: `simplicio_loop/exec_auth.py`
- Testes: `tests/test_exec_auth.py`
