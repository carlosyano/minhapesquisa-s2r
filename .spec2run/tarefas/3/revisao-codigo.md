# Revisão: código

## Achados
- [MELHORIA] apps/api/src/manutencao/limpeza-importacao.ts:79: se o segundo `contar` falhar, a chamada é `registrarFalha(i, antes, antes, ...)`, que grava `apagados=antes` e `restantes=antes`. Esse `apagados` não foi medido e também entra no resumo e no log da execução, inflando a contagem de apagados. Somado ao `restantes`, dá o dobro do que havia. Convém passar `apagados=0` (ou não afirmar contagem), como já é feito no `catch` externo de `executar`.
- [MELHORIA] apps/api/src/index.ts:4 e apps/api/src/infra/armazenamento.ts:90-121: os ganchos de teste `plantarObjeto`, `falharApagar` e `desfalharApagar` continuam no índice público do pacote e usam estado global do módulo. Só afetam o `ArmazenamentoEmMemoria`, usado só nos testes, e por isso não há risco em produção. Mesmo assim, convém expô-los pelo `test-harness`, como os outros ganchos (achado mantido da rodada anterior).
- [MELHORIA] apps/api/src/manutencao/limpeza-importacao.ts:72-83: só as chaves `1..total_paginas` são apagadas, mas `contar(pasta)` conta tudo o que está na pasta. Se sobrar na pasta um objeto com outro nome (por exemplo, um temporário do worker), a importação falha todo dia e nunca recebe `chave_storage` NULL. Essa escolha segura está de acordo com a RN-054 (1). Convém registrá-la como limitação conhecida no PLANO §12.3.

Achados da rodada anterior, conferidos um a um:
- BLOQUEANTE do lint em `armazenamento.ts:128`: corrigido. A instância agora é registrada por `registrarArmazenamento(this)` em `iniciar()`, sem `eslint-disable`. Na `evidencias/green-039.json`, o LINT terminou com código 0.
- `tick()` sem `catch` em `worker.ts`: corrigido (`worker.ts:166-171`). O `catch` registra só `e.name`.
- Linha `import_cleanup_failed` duplicada quando o banco está fora: corrigido. A falha da auditoria agora sai como `import_cleanup_audit_failed`, só com ids e a classe do erro.
- `apagados=0 restantes=0` fixos no `catch` externo: corrigido. O log não afirma mais contagens.
- Ganchos de teste no índice público: não corrigido. O achado continua como MELHORIA, acima.

Pontos conferidos sem achado:
- O filtro usa a lista fechada `estado IN ('concluida','falhou')` (RN-053 (3), ADR-002).
- As chaves são montadas só com `tenant_id`, `id` e `total_paginas` do banco, sem listar o armazenamento e sem usar o `chave_storage` (RN-054, ADR-001).
- A leitura entre tenants usa `mp_manutencao` só com colunas sem dado pessoal. As escritas passam por `noTenant`, com RLS (ADR-006).
- O `UPDATE` é parametrizado, tem a condição `chave_storage IS NOT NULL` e só roda com `restantes = 0`. Estado, `concluida_em`, aviso e formulário não mudam (RN-053 (4)).
- Importação sem resto não gera auditoria (RN-055 (2)). Há um único log de contagens por execução (RN-055 (3)).
- No erro, log e auditoria trazem só `e.name`, sem `e.message`, caminho nem chave (RN-028, ERR-046). O nome e a mensagem simulados do teste não vazam.
- O agendador usa o dia civil de `America/Sao_Paulo` pelo relógio injetado, marca o dia ao iniciar a execução e tem guarda de reentrada (CA-070, ADR-004). Ele está ligado no ciclo que já existe do `WorkerLeitura`, sem processo nem dependência nova.
- Não há injeção de SQL, segredo, dependência nova, supressão de alerta (`nosemgrep`, `eslint-disable`, `@ts-ignore`, `gitleaks:allow`) nem atalho para passar nos testes.
- Na `evidencias/green-039.json`, todos os passos terminaram com código 0: build, lint, 762 testes, SAST, gitleaks, `npm audit`, tipos, consistência, contrato e mutação.

Limitação: o DIFF_DA_TAREFA foi cortado em 40000 caracteres. Por isso, revisei o código direto no repositório e não consegui conferir pelo diff se o `package.json` e os testes aprovados ficaram intactos.

VEREDITO: APROVADO
