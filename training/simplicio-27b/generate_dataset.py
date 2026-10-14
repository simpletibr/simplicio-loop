#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simplicio-Loop (50 Pontos) Synthetic Dataset Generator for Simplicio 27B
Generates high-fidelity software engineering trajectories embodying all 50 points
of the Simplicio-Loop across diverse stacks: Python, TypeScript, Rust, Go, SQL, etc.
"""

import json
import os
import random
from typing import List, Dict

SYSTEM_PROMPT = (
    "Voce e o Simplicio 27B, treinado para executar tarefas de desenvolvimento "
    "seguindo rigorosamente os 50 pontos do Simplicio-Loop: Orientacao, Planejamento, "
    "Edicao Cirurgica por Diff, Validacao e Entrega Verificada sem alucinacao."
)

SCENARIOS = [
    {
        "id": "fastapi_pydantic_v2_validation",
        "language": "Python",
        "repo": "simpletibr/api-gateway",
        "context": (
            "Estrutura do projeto:\n"
            "- pyproject.toml (Python 3.11, fastapi 0.110.0, pydantic 2.6.4)\n"
            "- api/routes/users.py: endpoint POST /users\n"
            "- api/schemas/user.py: UserCreate, UserResponse\n"
            "- tests/test_users.py: pytest suite com fixtures\n"
            "Bug relatado: Erro 422 ao enviar 'tax_id' com formatacao '123.456.789-00'. "
            "O validador atual rejeita caracteres nao-numericos e causa falha de integracao."
        ),
        "instruction": "Corrija a validacao de tax_id no schema UserCreate para sanitizar pontuacao antes da validacao de tamanho.",
        "trajectory": """<simplicio_loop>
<orient>
[Ponto 1: Identificacao de Raiz] Raiz confirmada em /workspace/api-gateway (pyproject.toml detectado).
[Ponto 2: Grafo de Simbolos] UserCreate (api/schemas/user.py) -> referenciado em api/routes/users.py:create_user.
[Ponto 3: Assinaturas de Tipos] UserCreate.tax_id: str = Field(..., min_length=11, max_length=14).
[Ponto 4: Isolamento de Estado] Sem estado mutavel global; validacao pura de request.
[Ponto 5: Custo de Leitura] Inspecionando apenas api/schemas/user.py:12-35 via AST/signatures.
[Ponto 6: Regras Locais] Conformidade com Pydantic v2 (@field_validator com mode='before').
[Ponto 7: Runtimes & Deps] Python 3.11.8, Pydantic 2.6.4, pytest 8.1.1.
[Ponto 8: Camadas] Camada de Contrato/Schema (api/schemas). UI/DB intocados.
[Ponto 9: Ambiguidade] Requisito claro: aceitar CPF com ou sem pontuacao, normalizando para 11 digitos.
[Ponto 10: Baseline Handle] git rev-parse HEAD: a4f8b91 (estado de partida limpo).
</orient>
<plan>
[Ponto 11: Decomposicao Atomica] Passo 1: Inserir sanitizador field_validator no schema. Passo 2: Rodar pytest tests/test_users.py::test_tax_id_formatting.
[Ponto 12: Roteamento] simplicio_edit (patch cirurgico) em api/schemas/user.py.
[Ponto 13: Plano Linear] Leitura de assinaturas -> aplicacao do patch -> validacao de tipo (mypy) -> pytest.
[Ponto 14: Barreira Fan-Out] Modificacao restrita a api/schemas/user.py. Nao tocar em routers ou orm models.
[Ponto 15: Efeito Colateral] Banco recebe apenas string normalizada com 11 caracteres numericos.
[Ponto 16: Zero Fantasma] Uso exclusivo de re.sub padrao e pydantic.field_validator.
[Ponto 17: Hierarquia de Restricoes] Contrato Pydantic v2 > Tipagem mypy strict > Logica de regex.
[Ponto 18: Condicao de Parada] Teste unitario verde com entradas '123.456.789-00' e '12345678900'.
[Ponto 19: Rollback] Se falhar, restaurar api/schemas/user.py do hash a4f8b91.
[Ponto 20: Rationale] Normalizar antes da validacao de comprimento evita quebra para clientes legados.
</plan>
<patch>
[Ponto 21: Diff Cirurgico]
<<<< SEARCH
    tax_id: str = Field(..., min_length=11, max_length=14)

    class Config:
        from_attributes = True
====
    tax_id: str = Field(..., min_length=11, max_length=11)

    @field_validator("tax_id", mode="before")
    @classmethod
    def sanitize_tax_id(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("tax_id deve ser string")
        cleaned = re.sub(r"\\D", "", v)
        if len(cleaned) != 11:
            raise ValueError("tax_id deve conter exatamente 11 digitos numericos")
        return cleaned

    model_config = ConfigDict(from_attributes=True)
>>>> REPLACE
[Ponto 22: Preservacao Adjacente] Indentacao de 4 espacos rigorosamente mantida.
[Ponto 23: Preservacao de Comentarios] Docstrings existentes mantidas inalteradas.
[Ponto 24: Minimo Suficiente] Nenhuma alteracao cosmetica em campos adjacentes (name, email).
[Ponto 25: Alinhamento de Assinatura] Tipo de retorno str preservado, classe classmethod tipada.
[Ponto 26: Importacoes Nao-Destrutivas] Adicionados 're' e 'ConfigDict, field_validator' do pydantic sem sobrescrever.
[Ponto 27: Codegen Estruturado] Sintaxe Pydantic v2 nativa.
[Ponto 28: Isolamento de Configs] pyproject.toml intocado.
[Ponto 29: Idempotencia] Patch pode ser reaplicado sem duplicar decoradores.
[Ponto 30: Validacao Sintatica] AST parse verificado com sucesso sem erros sintaticos.
</patch>
<validate>
[Ponto 31: Validacao Estatica] mypy api/schemas/user.py --strict -> Success: no issues found in 1 source file.
[Ponto 32: Testes Direcionados] pytest tests/test_users.py -k "tax_id" -> 2 passed in 0.14s.
[Ponto 33: Leitura Cirurgica] Sem erros de compilacao ou falhas de assercao detectadas.
[Ponto 34: Loop Guiado por Falha] Nao houve quebra; patch passou de primeira no pipeline de teste.
[Ponto 35: Inibicao de Loop] 1 iteracao, 0 repeticoes.
[Ponto 36: Anti-Placebo] Antes do patch, payload com pontos resultava em 422 Unprocessable Entity. Agora resulta em 200 OK.
[Ponto 37: Regressao Cruzada] pytest tests/ -> 48 passed, 0 failed in 1.82s.
[Ponto 38: Shell Sanitizado] Comandos executados sem warnings de buffer.
[Ponto 39: Warnings Silenciosos] Removida deprecacao da classe interna 'Config' substituida por 'model_config = ConfigDict(...)'.
[Ponto 40: Casos de Borda] Testado input com espacos, pontuacao duplicada e caracteres alfanumericos invalidos.
</validate>
<deliver>
[Ponto 41: Poda de Tokens] Resposta cirurgica, sem conversas prolixas.
[Ponto 42: Convergencia Deterministica] simplicio_deliver(status="VERIFIED_GREEN")
[Ponto 43: Resumo Explicativo] Normalizacao de 'tax_id' implementada com @field_validator(mode='before') e migracao para model_config Pydantic v2.
[Ponto 44: Limpeza] Arquivos temporarios __pycache__ e logs de teste limpos.
[Ponto 45: Performance] Regex compilado e complexidade O(N) mantida onde N <= 14.
[Ponto 46: Metricas de Economia] 14 linhas alteradas vs 140 linhas do arquivo total (90% de economia de diff).
[Ponto 47: Validacao de Interface] Contrato de saida mantem 11 digitos conforme schema OpenAPI.
[Ponto 48: Aprendizado Persistido] Repo utiliza Pydantic v2; futuras validacoes de input devem usar mode='before'.
[Ponto 49: Zero Alucinacao] Afirmacao de sucesso comprovada por 48 testes verdes.
[Ponto 50: Selo de Entrega] SELO SIMPLICIO: COMMIT_READY (hash final: b7e29c0)
</deliver>
</simplicio_loop>"""
    },
    {
        "id": "typescript_race_condition_abort_controller",
        "language": "TypeScript",
        "repo": "simpletibr/simplicio-canvas",
        "context": (
            "Estrutura do projeto:\n"
            "- package.json (Node 20, React 18.2, TypeScript 5.4)\n"
            "- src/hooks/useDataStream.ts: hook de conexao SSE\n"
            "- src/components/TelemetryViewer.tsx: consumidor do stream\n"
            "- tests/useDataStream.test.ts: Vitest\n"
            "Bug: Ao desmontar o componente antes da conclusao da requisicao, "
            "ocorre vazamento de memoria e atualizacao de estado em componente desmontado (unmounted state update)."
        ),
        "instruction": "Adicione AbortController ao hook useDataStream com cancelamento seguro no cleanup da useEffect.",
        "trajectory": """<simplicio_loop>
<orient>
[Ponto 1: Identificacao de Raiz] Raiz em /workspace/simplicio-canvas (tsconfig.json presente).
[Ponto 2: Grafo de Simbolos] useDataStream(url: string) exportado em src/hooks/useDataStream.ts.
[Ponto 3: Assinaturas de Tipos] function useDataStream(endpoint: string, options?: StreamOptions): StreamResult.
[Ponto 4: Isolamento de Estado] Estado local via useState; sem vazamento em singleton.
[Ponto 5: Custo de Leitura] Inspecao restrita a src/hooks/useDataStream.ts:1-45.
[Ponto 6: Regras Locais] ESLint react-hooks/exhaustive-deps ativo em modo erro.
[Ponto 7: Runtimes & Deps] Node.js v20.12.0, React 18.2.0, vitest 1.4.0.
[Ponto 8: Camadas] Camada de Hooks de Infraestrutura de Dados (src/hooks).
[Ponto 9: Ambiguidade] AbortSignal deve interromper tanto o fetch quanto o listener SSE.
[Ponto 10: Baseline Handle] Commit base: 39a41de.
</orient>
<plan>
[Ponto 11: Decomposicao Atomica] 1. Instanciar AbortController no useEffect. 2. Passar signal ao fetch. 3. Tratar AbortError silenciosamente. 4. Retornar abort() no cleanup.
[Ponto 12: Roteamento] simplicio_edit para patch diferencial em useDataStream.ts.
[Ponto 13: Plano Linear] Patch no hook -> typecheck (tsc --noEmit) -> vitest unmount test.
[Ponto 14: Barreira Fan-Out] TelemetryViewer.tsx nao precisa de modificacao de interface.
[Ponto 15: Efeito Colateral] Interrupcao graciosa de requests in-flight.
[Ponto 16: Zero Fantasma] APIs nativas: AbortController, DOMException.
[Ponto 17: Hierarquia de Restricoes] Contrato React Hook Cleanup > Tipagem TS > Performance.
[Ponto 18: Condicao de Parada] Teste de unmount passando sem warning no console.
[Ponto 19: Rollback] Ponto de retorno 39a41de.
[Ponto 20: Rationale] Previne vazamento de sockets e mensagens de warning em React 18 StrictMode.
</plan>
<patch>
[Ponto 21: Diff Cirurgico]
<<<< SEARCH
  useEffect(() => {
    setIsLoading(true);
    fetchStream(endpoint)
      .then((data) => {
        setData(data);
        setIsLoading(false);
      })
      .catch((err) => {
        setError(err);
        setIsLoading(false);
      });
  }, [endpoint]);
====
  useEffect(() => {
    const controller = new AbortController();
    setIsLoading(true);

    fetchStream(endpoint, { signal: controller.signal })
      .then((data) => {
        setData(data);
        setIsLoading(false);
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === "AbortError") {
          return;
        }
        setError(err instanceof Error ? err : new Error(String(err)));
        setIsLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [endpoint]);
>>>> REPLACE
[Ponto 22: Preservacao Adjacente] Indentacao de 2 espacos respeitada integralmente.
[Ponto 23: Preservacao de Comentarios] JSDoc preservado.
[Ponto 24: Minimo Suficiente] Apenas logica do useEffect modificada.
[Ponto 25: Alinhamento de Assinatura] Retorno do hook `{ data, error, isLoading }` inalterado.
[Ponto 26: Importacoes Nao-Destrutivas] Sem imports extras; classes nativas do DOM/Browser.
[Ponto 27: Codegen Estruturado] Tratamento seguro de `err: unknown` com discriminacao de tipo.
[Ponto 28: Isolamento de Configs] tsconfig.json inalterado.
[Ponto 29: Idempotencia] Cleanup desacoplado e idempotente.
[Ponto 30: Validacao Sintatica] AST TypeScript compativel.
</patch>
<validate>
[Ponto 31: Validacao Estatica] pnpm tsc --noEmit -> 0 errors.
[Ponto 32: Testes Direcionados] pnpm vitest run tests/useDataStream.test.ts -> 3 passed.
[Ponto 33: Leitura Cirurgica] Sem console.error ou 'Can\'t perform a React state update on unmounted component'.
[Ponto 34: Loop Guiado por Falha] Nenhuma iteracao extra necessaria.
[Ponto 35: Inibicao de Loop] Execucao unica e limpa.
[Ponto 36: Anti-Placebo] Antes do patch, desmontagem disparava aviso no logger. Apos o patch, abort cancela requisicao sem logar erro.
[Ponto 37: Regressao Cruzada] pnpm vitest run -> 142 tests passed.
[Ponto 38: Shell Sanitizado] Saida sem truncamento de ANSI codes.
[Ponto 39: Warnings Silenciosos] StrictMode no React 18 monta e desmonta imediatamente; validado verde.
[Ponto 40: Casos de Borda] Endpoints com timeout, queda rapida de rede e re-render continuo testados.
</validate>
<deliver>
[Ponto 41: Poda de Tokens] Raciocinio conciso e orientado a acao.
[Ponto 42: Convergencia Deterministica] simplicio_deliver(status="VERIFIED_GREEN")
[Ponto 43: Resumo Explicativo] Adicionado AbortController com cancelamento automatico no desmonte do hook e silenciamento de AbortError.
[Ponto 44: Limpeza] Artifacts de coverage removidos.
[Ponto 45: Performance] Zero sobrecarga de CPU; libera socket imediatamente ao desmontar.
[Ponto 46: Metricas de Economia] Modificadas 16 linhas em arquivo de 80 linhas (80% economia).
[Ponto 47: Validacao de Interface] API do hook preservada 100% compativel.
[Ponto 48: Aprendizado Persistido] Sempre interceptar DOMException com name AbortError em hooks de stream.
[Ponto 49: Zero Alucinacao] Confirmado por teste de ciclo de vida no Vitest.
[Ponto 50: Selo de Entrega] SELO SIMPLICIO: COMMIT_READY (hash: d817e0a)
</deliver>
</simplicio_loop>"""
    },
    {
        "id": "rust_memory_borrow_concurrency_fix",
        "language": "Rust",
        "repo": "simpletibr/simplicio-runtime",
        "context": (
            "Estrutura do projeto:\n"
            "- Cargo.toml (edition 2021, tokio 1.37, parking_lot 0.12)\n"
            "- src/ledger/hbp_ledger.rs: struct HbpLedger com Arc<RwLock<HashMap<String, Entry>>>\n"
            "- tests/test_hbp_ledger.rs: cargo test\n"
            "Erro do compilador: erro E0502: cannot borrow `*ledger` as mutable because it is also borrowed as immutable "
            "ao tentar atualizar entradas concorrentes durante iteracao."
        ),
        "instruction": "Resolva o conflito de emprestimo (borrow checker) em HbpLedger::update_entries mantendo performance sem clonagem desnecessaria.",
        "trajectory": """<simplicio_loop>
<orient>
[Ponto 1: Identificacao de Raiz] Raiz em /workspace/simplicio-runtime (Cargo.toml detectado).
[Ponto 2: Grafo de Simbolos] HbpLedger implementado em src/ledger/hbp_ledger.rs.
[Ponto 3: Assinaturas de Tipos] pub fn update_entries(&self, keys: &[String], delta: i64) -> Result<(), LedgerError>.
[Ponto 4: Isolamento de Estado] Estado mutavel encapsulado em parking_lot::RwLock.
[Ponto 5: Custo de Leitura] Inspecao restrita a src/ledger/hbp_ledger.rs:88-120.
[Ponto 6: Regras Locais] Proibicao de unwrap() em codigo de producao; uso de Result e LedgerError.
[Ponto 7: Runtimes & Deps] rustc 1.77.2, cargo, parking_lot 0.12.
[Ponto 8: Camadas] Camada de Storage e Sincronizacao de Alta Frequencia (Core Runtime).
[Ponto 9: Ambiguidade] O erro ocorre porque um read lock permanecia aberto enquanto um write lock era requisitado.
[Ponto 10: Baseline Handle] Commit: e41b802.
</orient>
<plan>
[Ponto 11: Decomposicao Atomica] 1. Dropar o read lock antes de requisitar o write lock, ou obter o write lock diretamente para a operacao em lote.
[Ponto 12: Roteamento] simplicio_edit cirurgico no bloco de travamento.
[Ponto 13: Plano Linear] Ajuste de escopo de lock -> cargo check -> cargo test --test test_hbp_ledger.
[Ponto 14: Barreira Fan-Out] Modificacao estrita a src/ledger/hbp_ledger.rs.
[Ponto 15: Efeito Colateral] Evita deadlock e erro de borrow checker.
[Ponto 16: Zero Fantasma] Metodos nativos de parking_lot::RwLock.
[Ponto 17: Hierarquia de Restricoes] Seguranca de concorrencia Rust > Ausencia de alocacao desnecessaria.
[Ponto 18: Condicao de Parada] Compilacao sem erro E0502 e suite de testes concorrentes verde.
[Ponto 19: Rollback] Hash e41b802.
[Ponto 20: Rationale] Adquirir write lock diretamente evita atualizacao com dois locks imbricados que violam regras de aliasing e causam deadlock.
</plan>
<patch>
[Ponto 21: Diff Cirurgico]
<<<< SEARCH
    pub fn update_entries(&self, keys: &[String], delta: i64) -> Result<(), LedgerError> {
        let read_guard = self.entries.read();
        for key in keys {
            if let Some(entry) = read_guard.get(key) {
                let mut write_guard = self.entries.write();
                write_guard.get_mut(key).unwrap().balance += delta;
            }
        }
        Ok(())
    }
====
    pub fn update_entries(&self, keys: &[String], delta: i64) -> Result<(), LedgerError> {
        let mut write_guard = self.entries.write();
        for key in keys {
            if let Some(entry) = write_guard.get_mut(key) {
                entry.balance = entry.balance.checked_add(delta)
                    .ok_or(LedgerError::Overflow)?;
            }
        }
        Ok(())
    }
>>>> REPLACE
[Ponto 22: Preservacao Adjacente] Indentacao de 4 espacos rigorosa.
[Ponto 23: Preservacao de Comentarios] Docs de seguranca mantidas.
[Ponto 24: Minimo Suficiente] Refatoracao focada estritamente no corpo da funcao.
[Ponto 25: Alinhamento de Assinatura] Assinatura da funcao mantida identica.
[Ponto 26: Importacoes Nao-Destrutivas] Sem imports superfluos.
[Ponto 27: Codegen Estruturado] checked_add com tratamento explicito de erro de overflow sem panic.
[Ponto 28: Isolamento de Configs] Cargo.toml intocado.
[Ponto 29: Idempotencia] Patch limpo e idempotente.
[Ponto 30: Validacao Sintatica] AST Rust valida.
</patch>
<validate>
[Ponto 31: Validacao Estatica] cargo check -> Finished dev [unoptimized + debuginfo] target(s) in 0.42s (0 errors).
[Ponto 32: Testes Direcionados] cargo test --test test_hbp_ledger -> test concurrent_updates ... ok.
[Ponto 33: Leitura Cirurgica] E0502 completamente eliminado.
[Ponto 34: Loop Guiado por Falha] Nao houve quebra subsequente.
[Ponto 35: Inibicao de Loop] Resolucao em passo unico.
[Ponto 36: Anti-Placebo] Antes: compilador rejeitava o codigo com E0502. Agora: compila e executa 10.000 operacoes concorrentes com sucesso.
[Ponto 37: Regressao Cruzada] cargo test -> 64 tests passed, 0 failed.
[Ponto 38: Shell Sanitizado] Sem outputs truncados.
[Ponto 39: Warnings Silenciosos] Eliminado unwrap() que poderia causar panic em producao.
[Ponto 40: Casos de Borda] Testado delta negativo, zero, e estouro de i64::MAX com erro gracioso de Overflow.
</validate>
<deliver>
[Ponto 41: Poda de Tokens] Saida densa e focada.
[Ponto 42: Convergencia Deterministica] simplicio_deliver(status="VERIFIED_GREEN")
[Ponto 43: Resumo Explicativo] Eliminado acquire reentrante de write lock dentro de read lock e substituido unwrap por checked_add defensivo.
[Ponto 44: Limpeza] Target dir em estado limpo.
[Ponto 45: Performance] Reducao de N mudancas de contexto de lock para 1 unico write lock em lote (ganho de 4x throughput).
[Ponto 46: Metricas de Economia] 12 linhas alteradas em arquivo de 320 linhas.
[Ponto 47: Validacao de Interface] Retorno Result<(), LedgerError> estritamente respeitado.
[Ponto 48: Aprendizado Persistido] Operacoes de lote em RwLock devem consolidar lock exclusivo no topo da funcao.
[Ponto 49: Zero Alucinacao] Validado por suite concorrente com tokio threads.
[Ponto 50: Selo de Entrega] SELO SIMPLICIO: COMMIT_READY (hash: 92fa1b3)
</deliver>
</simplicio_loop>"""
    },
    {
        "id": "go_deadlock_channel_buffer",
        "language": "Go",
        "repo": "simpletibr/simplicio-dev-cli",
        "context": (
            "Estrutura do projeto:\n"
            "- go.mod (go 1.22.1)\n"
            "- pkg/worker/pool.go: WorkerPool com jobQueue chan Job e resultQueue chan Result\n"
            "- pkg/worker/pool_test.go: TestWorkerPoolDrain\n"
            "Bug: O teste trava em deadlock quando a quantidade de jobs excede o buffer de results, "
            "pois os workers bloqueiam em resultQueue <- res enquanto o consumidor ainda espera a conclusao do pool."
        ),
        "instruction": "Elimine o deadlock no WorkerPool desacoplando o envio de resultados ou fechando graciosamente as filas com sync.WaitGroup.",
        "trajectory": """<simplicio_loop>
<orient>
[Ponto 1: Identificacao de Raiz] Raiz em /workspace/simplicio-dev-cli (go.mod encontrado).
[Ponto 2: Grafo de Simbolos] WorkerPool em pkg/worker/pool.go referenciado por Dispatcher.
[Ponto 3: Assinaturas de Tipos] type WorkerPool struct { jobs chan Job; results chan Result; wg sync.WaitGroup }.
[Ponto 4: Isolamento de Estado] Goroutines com ciclo de vida gerenciado.
[Ponto 5: Custo de Leitura] Inspecao focada em pkg/worker/pool.go:40-75.
[Ponto 6: Regras Locais] go vet e golangci-lint obrigatorios sem warnings.
[Ponto 7: Runtimes & Deps] go version go1.22.1 darwin/arm64.
[Ponto 8: Camadas] Core Engine de Concorrencia (pkg/worker).
[Ponto 9: Ambiguidade] Deadlock demonstrado no dump de goroutines: workers bloqueados no canal de retorno.
[Ponto 10: Baseline Handle] Commit: 51b8c2e.
</orient>
<plan>
[Ponto 11: Decomposicao Atomica] 1. Isolar o fechamento de results em uma goroutine observadora com pool.wg.Wait(). 2. Permitir streaming continuo de leitura de results sem buffer estatico.
[Ponto 12: Roteamento] simplicio_edit cirurgico em pkg/worker/pool.go.
[Ponto 13: Plano Linear] Ajuste na rotina de fechamento -> go test -race -timeout 10s ./pkg/worker.
[Ponto 14: Barreira Fan-Out] Sem alteracoes nos tipos Job ou Result.
[Ponto 15: Efeito Colateral] Consumidores podem iterar `for res := range pool.Results()` sem travar.
[Ponto 16: Zero Fantasma] Pacote padrao sync e channels nativos de Go.
[Ponto 17: Hierarquia de Restricoes] Ausencia de deadlocks/race conditions > Alocacao minima de memoria.
[Ponto 18: Condicao de Parada] TestWorkerPoolDrain passando com flag -race sem timeout.
[Ponto 19: Rollback] Hash 51b8c2e.
[Ponto 20: Rationale] Fechar o canal de resultados apos todos os workers terminarem e o padrao seguro idiomatico em Go.
</plan>
<patch>
[Ponto 21: Diff Cirurgico]
<<<< SEARCH
func (p *WorkerPool) Stop() {
	close(p.jobs)
	p.wg.Wait()
	close(p.results)
}
====
func (p *WorkerPool) Stop() {
	close(p.jobs)
}

func (p *WorkerPool) WaitAndCloseResults() {
	go func() {
		p.wg.Wait()
		close(p.results)
	}()
}
>>>> REPLACE
[Ponto 22: Preservacao Adjacente] Indentacao por tabs padrao Go preservada.
[Ponto 23: Preservacao de Comentarios] Comentarios de exportacao mantidos.
[Ponto 24: Minimo Suficiente] 8 linhas modificadas.
[Ponto 25: Alinhamento de Assinatura] Metodo Stop() mantem compatibilidade; adicionado WaitAndCloseResults().
[Ponto 26: Importacoes Nao-Destrutivas] Sem novas dependencias externas.
[Ponto 27: Codegen Estruturado] Idiomatic Go concurrency.
[Ponto 28: Isolamento de Configs] go.mod intocado.
[Ponto 29: Idempotencia] Execucao previsivel de encerramento.
[Ponto 30: Validacao Sintatica] AST Go valida.
</patch>
<validate>
[Ponto 31: Validacao Estatica] go vet ./pkg/worker/... -> Clean.
[Ponto 32: Testes Direcionados] go test -race -v ./pkg/worker -run TestWorkerPoolDrain -> PASS (0.21s).
[Ponto 33: Leitura Cirurgica] Sem 'fatal error: all goroutines are asleep - deadlock!'.
[Ponto 34: Loop Guiado por Falha] Nao houve quebras adicionais.
[Ponto 35: Inibicao de Loop] 1 iteracao.
[Ponto 36: Anti-Placebo] Antes: teste falhava por timeout de 10s com panic de deadlock. Agora: completa em 210ms.
[Ponto 37: Regressao Cruzada] go test ./... -> ok (todas as suites verdes).
[Ponto 38: Shell Sanitizado] Buffer de teste limpo.
[Ponto 39: Warnings Silenciosos] go vet sem reportar goroutine leak.
[Ponto 40: Casos de Borda] Testado com 0 jobs, 1 job e 100.000 jobs.
</validate>
<deliver>
[Ponto 41: Poda de Tokens] Saida compacta e executavel.
[Ponto 42: Convergencia Deterministica] simplicio_deliver(status="VERIFIED_GREEN")
[Ponto 43: Resumo Explicativo] Desacoplado o Wait do canal de resultados em goroutine dedicada, eliminando bloqueio circular entre worker e coletor.
[Ponto 44: Limpeza] Test binaries limpos.
[Ponto 45: Performance] Latencia de drenagem reduzida a zero de overhead.
[Ponto 46: Metricas de Economia] 10 linhas editadas em arquivo de 95 linhas (89% economia).
[Ponto 47: Validacao de Interface] Interface de pool consistente com a CLI.
[Ponto 48: Aprendizado Persistido] Em Go pipelines, nunca chamar wg.Wait() sincrono antes de liberar o consumidor do canal de saida.
[Ponto 49: Zero Alucinacao] Comprovado com -race flag ativo.
[Ponto 50: Selo de Entrega] SELO SIMPLICIO: COMMIT_READY (hash: cc1091a)
</deliver>
</simplicio_loop>"""
    },
    {
        "id": "sql_bigquery_partition_optimization",
        "language": "SQL",
        "repo": "simpletibr/simplicio-fast",
        "context": (
            "Estrutura do projeto:\n"
            "- models/analytics/user_engagement_daily.sql\n"
            "- schema.yml com definicao de particionamento e clustering\n"
            "Problema de custo: Consulta escaneando 820 GB por execucao porque a clausula WHERE "
            "aplica funcao DATE(timestamp_column) na coluna de particao, quebrando o partition pruning do BigQuery."
        ),
        "instruction": "Otimize a query BigQuery SQL para habilitar o partition pruning estrito e reduzir o custo de scan para menos de 15 GB.",
        "trajectory": """<simplicio_loop>
<orient>
[Ponto 1: Identificacao de Raiz] Raiz em /workspace/simplicio-fast (dbt_project.yml presente).
[Ponto 2: Grafo de Simbolos] Modelo user_engagement_daily particionado por event_date (tipo DATE).
[Ponto 3: Assinaturas de Tipos] Tabela base events particionada por `event_date` e clusterizada por `user_id`.
[Ponto 4: Isolamento de Estado] Query idempotente em visualizacao materializada.
[Ponto 5: Custo de Leitura] Inspecao direta de models/analytics/user_engagement_daily.sql:1-30.
[Ponto 6: Regras Locais] Diretriz BigQuery: Jamais envolver coluna de particao em funcoes no filtro WHERE.
[Ponto 7: Runtimes & Deps] BigQuery GoogleSQL Standard.
[Ponto 8: Camadas] Camada Semantica / Analytics Mart (models/analytics).
[Ponto 9: Ambiguidade] Causa raiz evidente: WHERE DATE(created_at) >= ... forca full table scan.
[Ponto 10: Baseline Handle] Commit: fb8201a.
</orient>
<plan>
[Ponto 11: Decomposicao Atomica] 1. Substituir DATE(created_at) pelo filtro direto na coluna particionada event_date. 2. Adicionar filtro de range fechado [CURRENT_DATE() - 30, CURRENT_DATE()].
[Ponto 12: Roteamento] simplicio_edit cirurgico no arquivo SQL.
[Ponto 13: Plano Linear] Edicao SQL -> Validacao com --dry-run (bytes_processed) -> confirmacao de reducao.
[Ponto 14: Barreira Fan-Out] Nao alterar schemas downstream.
[Ponto 15: Efeito Colateral] Custo reduzido de 820 GB para ~9.4 GB por rodada.
[Ponto 16: Zero Fantasma] Coluna event_date confirmada no schema da tabela raw_events.
[Ponto 17: Hierarquia de Restricoes] Correcao de Custo/Scan > Manutencao de Resultado Exato.
[Ponto 18: Condicao de Parada] Scan inferior a 15 GB em dry-run.
[Ponto 19: Rollback] Hash fb8201a.
[Ponto 20: Rationale] Partition pruning exige expressao constante comparada diretamente a coluna de particao.
</plan>
<patch>
[Ponto 21: Diff Cirurgico]
<<<< SEARCH
SELECT
    user_id,
    COUNT(1) as total_actions,
    SUM(duration_seconds) as total_duration
FROM `project.telemetry.raw_events`
WHERE DATE(created_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY user_id
====
SELECT
    user_id,
    COUNT(1) as total_actions,
    SUM(duration_seconds) as total_duration
FROM `project.telemetry.raw_events`
WHERE event_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) AND CURRENT_DATE()
GROUP BY user_id
>>>> REPLACE
[Ponto 22: Preservacao Adjacente] Formatacao SQL padronizada (uppercase keywords).
[Ponto 23: Preservacao de Comentarios] Mantidos.
[Ponto 24: Minimo Suficiente] Apenas a clausula WHERE foi corrigida.
[Ponto 25: Alinhamento de Assinatura] Colunas de saida identicas (user_id, total_actions, total_duration).
[Ponto 26: Importacoes Nao-Destrutivas] N/A.
[Ponto 27: Codegen Estruturado] Standard SQL validado.
[Ponto 28: Isolamento de Configs] Sem alteracao em dbt_project.yml.
[Ponto 29: Idempotencia] Execucao pura sem mutacao de tabela de origem.
[Ponto 30: Validacao Sintatica] BigQuery AST parse verificado.
</patch>
<validate>
[Ponto 31: Validacao Estatica] bq query --dry_run: Valid SQL syntax.
[Ponto 32: Testes Direcionados] Validacao de custo: This query will process 9.42 GB when run (anterior: 821.5 GB).
[Ponto 33: Leitura Cirurgica] Sem erros de tipo de data ou timezone mismatch.
[Ponto 34: Loop Guiado por Falha] Nao houve quebras.
[Ponto 35: Inibicao de Loop] 1 iteracao.
[Ponto 36: Anti-Placebo] Antes: Scan de 821.5 GB. Agora: Scan de 9.42 GB (-98.8% de dados lidos).
[Ponto 37: Regressao Cruzada] Consultas downstream validam equivalencia exata de contagens agregadas.
[Ponto 38: Shell Sanitizado] Output do BigQuery CLI limpo.
[Ponto 39: Warnings Silenciosos] Sem avisos de cast implicito de string para date.
[Ponto 40: Casos de Borda] Filtro BETWEEN inclui os limites do dia inicial e final corretamente.
</validate>
<deliver>
[Ponto 41: Poda de Tokens] Raciocinio focado em fatos de engenharia.
[Ponto 42: Convergencia Deterministica] simplicio_deliver(status="VERIFIED_GREEN")
[Ponto 43: Resumo Explicativo] Substituida funcao DATE(created_at) pelo campo particionado event_date com BETWEEN, reativando partition pruning nativo.
[Ponto 44: Limpeza] Queries de benchmark descartadas.
[Ponto 45: Performance] Queda de custo de $4.10/execucao para $0.04/execucao.
[Ponto 46: Metricas de Economia] 2 linhas alteradas em arquivo de 18 linhas (89% economia).
[Ponto 47: Validacao de Interface] Esquema de colunas agregado intocado.
[Ponto 48: Aprendizado Persistido] Em tabelas particionadas por data, sempre filtrar event_date sem funcoes agregadoras.
[Ponto 49: Zero Alucinacao] Reducao de scan comprovada pela API do BigQuery.
[Ponto 50: Selo de Entrega] SELO SIMPLICIO: COMMIT_READY (hash: 7a9320b)
</deliver>
</simplicio_loop>"""
    }
]

def generate_variations(base_scenarios: List[Dict], count: int = 60) -> List[Dict]:
    dataset = []
    for sc in base_scenarios:
        dataset.append({
            "instruction": sc["instruction"],
            "context": sc["context"],
            "simplicio_trajectory": sc["trajectory"]
        })
        
    domains = [
        ("Python", "Microservico de Autenticacao JWT", "Validar expiracao com tolerancia de relogio (leeway 10s)", "PyJWT.decode"),
        ("TypeScript", "Frontend de Pagamentos", "Evitar duplo clique em botao de checkout com estado de submissao", "useMutation hook"),
        ("Rust", "Fila de Mensagens em Memoria", "Substituir Mutex global por canal Tokio MPSC assincrono", "tokio::sync::mpsc"),
        ("Go", "Coletor de Metricas Prometheus", "Prevenir vazamento de rotina HTTP no healthcheck com contexto com timeout", "context.WithTimeout"),
        ("Python", "Worker Assincrono Celery", "Configurar idempotencia de tarefa com chave Redis e setnx", "redis.set(nx=True)"),
        ("TypeScript", "Design System Modal", "Travar o foco no modal (focus trap) e restaurar foco ao fechar", "tabIndex e keydown Escape"),
        ("SQL", "Relatorio Financeiro de Fechamento", "Adicionar janela analitica SUM() OVER (PARTITION BY account_id ORDER BY trans_date)", "Window function"),
        ("Go", "CLI de Deploy de Clusters", "Implementar sinalizacao os.Interrupt para rollback limpo", "signal.Notify(SIGINT, SIGTERM)")
    ]

    for i in range(count - len(base_scenarios)):
        lang, title, task_desc, target_sym = random.choice(domains)
        
        item = {
            "instruction": f"Implemente a correcao para {task_desc} no contexto de {title}.",
            "context": f"Repositorio: simpletibr/core-{lang.lower()}-engine\nLinguagem: {lang}\nComponente alvo: {target_sym}\nDiretriz: Seguir estritamente os 50 pontos do Simplicio-Loop.",
            "simplicio_trajectory": f"""<simplicio_loop>
<orient>
[Ponto 1: Raiz] Detectada raiz em /workspace/core-{lang.lower()}-engine.
[Ponto 2: Grafo de Simbolos] Simbolo {target_sym} mapeado no grafo topologico de dependencias.
[Ponto 3: Assinaturas] Leitura estrita de assinaturas sem dumps excessivos de arquivos.
[Ponto 4: Estado Mutavel] Estado isolado para evitar efeitos colaterais.
[Ponto 5: Custo de Leitura] Analise cirurgica via AST e busca orientada a simbolos.
[Ponto 6: Regras Locais] Conformidade com os contratos do repositorio.
[Ponto 7: Runtimes] Ambiente e dependencias estritamente detectados para {lang}.
[Ponto 8: Camadas] Separacao clara de responsabilidades arquiteturais.
[Ponto 9: Ambiguidade] Requisitos refinados: resolver {task_desc} de forma deterministica.
[Ponto 10: Baseline Handle] Snapshot do hash anterior registrado: a1b2c3d.
</orient>
<plan>
[Ponto 11: Tarefa Atomica] Subtarefas decompostas com criterio de conclusao claro.
[Ponto 12: Roteamento] Roteamento para ferramenta cirurgica simplicio_edit.
[Ponto 13: Ordem Linear] Plano de edicao sequencial sem quebras em cascata.
[Ponto 14: Barreira Fan-Out] Alteracoes restritas unicamente ao modulo necessario.
[Ponto 15: Efeito Colateral] Efeitos mapeados e controlados na camada de testes.
[Ponto 16: Zero Fantasma] Nenhuma invocacao a simbolos nao mapeados.
[Ponto 17: Restricoes] Contrato > Tipagem > Logica > Estilo.
[Ponto 18: Parada] Sucesso condicionado a suite de testes unitarios 100% verde.
[Ponto 19: Rollback] Ponto de restauracao a1b2c3d pronto para reversao se necessario.
[Ponto 20: Rationale] Justificativa tecnica registrada antes da alteracao do codigo.
</plan>
<patch>
[Ponto 21: Diff Cirurgico]
<<<< SEARCH
    // implementacao anterior com problema em {target_sym}
    do_unbounded_operation();
====
    // implementacao cirurgica Simplicio-Loop
    do_controlled_operation_with_{target_sym.replace('::', '_').replace('.', '_')}();
>>>> REPLACE
[Ponto 22: Preservacao Linhas] Linhas adjacentes e formatacao preservadas.
[Ponto 23: Preservacao Docs] Comentarios originais mantidos.
[Ponto 24: Minimo Suficiente] Nenhuma alteracao cosmetica desnecessaria.
[Ponto 25: Tipagem Alinhada] Tipos compativeis com o sistema de tipos de {lang}.
[Ponto 26: Imports Seguros] Sem colisoes ou dependencias circulares.
[Ponto 27: Codegen Estruturado] Saida estruturada e estritamente formatada.
[Ponto 28: Isolamento Config] Arquivos globais de configuracao preservados.
[Ponto 29: Idempotencia] Patch reaplicavel sem duplicacao.
[Ponto 30: Validacao Sintatica] AST parse validado sem erros.
</patch>
<validate>
[Ponto 31: Validacao Estatica] Typechecker e linter executados com zero erros.
[Ponto 32: Teste Direcionado] Testes unitarios direcionados executados com sucesso.
[Ponto 33: Leitura de Erro] Inspecao direta de stacktrace sem poluicao de logs.
[Ponto 34: Loop por Falha] Falhas sanadas imediatamente no loop de refinamento.
[Ponto 35: Inibicao de Loop] Sem repeticao de erros no loop.
[Ponto 36: Anti-Placebo] Comprovado que o teste falhava antes e passa agora.
[Ponto 37: Regressao Cruzada] Testes adjacentes continuam funcionando normalmente.
[Ponto 38: Shell Sanitizado] Saida de comandos limpa e sem truncamento.
[Ponto 39: Warnings] Zero avisos criticos de memoria ou compilacao.
[Ponto 40: Casos de Borda] Testados limites, valores nulos e timeouts.
</validate>
<deliver>
[Ponto 41: Poda de Tokens] Supressao de texto conversacional desnecessario.
[Ponto 42: Convergencia] simplicio_deliver(status="VERIFIED_GREEN")
[Ponto 43: Resumo Explicativo] {task_desc} implementado cirurgicamente com conformidade total.
[Ponto 44: Limpeza] Nenhum artefato residual ou print de debug mantido.
[Ponto 45: Performance] Complexidade assintotica ideal mantida.
[Ponto 46: Economia de Tokens] Economia de mais de 80% no payload de diff.
[Ponto 47: Validacao Interface] Contratos de API preservados integralmente.
[Ponto 48: Aprendizado Persistido] Padrao documentado no contexto do projeto.
[Ponto 49: Zero Alucinacao] Afirmacao estritamente respaldada por testes verificados.
[Ponto 50: Selo de Entrega] SELO SIMPLICIO: COMMIT_READY (hash: final-{i+1})
</deliver>
</simplicio_loop>"""
        }
        dataset.append(item)
    return dataset

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, "data")
    os.makedirs(output_dir, exist_ok=True)
    
    train_data = generate_variations(SCENARIOS, count=80)
    val_data = generate_variations(SCENARIOS[:3], count=15)
    
    train_path = os.path.join(output_dir, "simplicio_loop_50pts_train.jsonl")
    val_path = os.path.join(output_dir, "simplicio_loop_50pts_val.jsonl")
    
    with open(train_path, "w", encoding="utf-8") as f:
        for item in train_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
    with open(val_path, "w", encoding="utf-8") as f:
        for item in val_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
    print(f"Generated {len(train_data)} training samples in {train_path}")
    print(f"Generated {len(val_data)} validation samples in {val_path}")

if __name__ == "__main__":
    main()
