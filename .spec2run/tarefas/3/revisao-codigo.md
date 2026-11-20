# Revisão: código

## Achados
- [BLOQUEANTE] apps/api/src/infra/armazenamento.ts:128: a linha nova `ultimoArmazenamento = this;` (gancho `plantarObjeto` dos testes) quebra o lint. Na evidência GREEN (`evidencias/green-036.json`), o passo LINT terminou com código 1: `128:5 error Unexpected aliasing of 'this' to local variable @typescript-eslint/no-this-alias`. O CI precisa ficar todo verde (AGENTS §3, passo 4), e o erro vem do código desta tarefa. Para corrigir, guarde a referência sem copiar o `this` para uma variável do módulo. Por exemplo, registre a instância numa função ou no construtor do harness. Não vale suprimir a regra com `eslint-disable`.
- [MELHORIA] apps/api/src/leitura/worker.ts:166: o `await this.agendador.tick()` não tem `catch`. Uma falha geral do job sobe e interrompe as leituras, a importação e a exportação daquele ciclo. Exemplos: o `SELECT` em `banco.manutencao` falha, ou a gravação do log final falha. O DESIGN (Componentes, `main.ts`) pede um `catch` próprio que registre só o nome da classe do erro. O dia já fica marcado, então isso só acontece uma vez por dia. Ainda assim, convém isolar o job do resto do ciclo (ERR-046: "a limpeza das demais [...] segue").
- [MELHORIA] apps/api/src/index.ts:4 e apps/api/src/infra/armazenamento.ts:90-116: os ganchos de teste `plantarObjeto`, `falharApagar` e `desfalharApagar` ficam no índice público do pacote de produção e usam estado global do módulo. Hoje só afetam o `ArmazenamentoEmMemoria`, que existe só nos testes, e por isso não há risco em produção. Mesmo assim, convém exportá-los pelo `test-harness`, como os outros ganchos, para manter a injeção de falhas fora da superfície de produção.
- [MELHORIA] apps/api/src/manutencao/limpeza-importacao.ts:113-117: quando o banco está fora, a mesma falha gera duas linhas `import_cleanup_failed`. Na segunda, `erro=` traz a classe do erro do banco, e não a do armazenamento. Isso não fere a RN-028, porque a linha só tem identificadores e contagens. Porém, o ERR-046 prevê um registro por falha, e as duas linhas confundem a contagem. Convém registrar uma linha só, com as duas classes, ou usar outro evento para a falha da auditoria.
- [MELHORIA] apps/api/src/manutencao/limpeza-importacao.ts:52: o `catch` externo grava `apagados=0 restantes=0` fixos. Na prática esse caminho não é alcançado, porque `limpar` já captura as próprias falhas. Mesmo assim, convém não afirmar contagens que não foram medidas.

Pontos conferidos sem achado:
- O filtro usa a lista fechada `estado IN ('concluida','falhou')` (RN-053 (3), ADR-002).
- As chaves são montadas só com `tenant_id`, `id` e `total_paginas` do banco, sem listar o armazenamento e sem usar o `chave_storage` (RN-054, ADR-001).
- O prefixo de `contar` termina em `/`, então a importação `.../1/` não alcança a `.../10/`.
- A leitura entre tenants usa `mp_manutencao` só com colunas sem dado pessoal. As escritas passam por `noTenant`, com RLS (ADR-006).
- O `UPDATE` é parametrizado e tem a condição `chave_storage IS NOT NULL`. O estado e os demais campos não mudam (RN-053 (4)).
- Importação sem resto não gera auditoria (RN-055 (2)). Há um único log de contagens por execução (RN-055 (3)).
- No erro, log e auditoria trazem só `e.name`, sem `e.message`, caminho nem chave (RN-028, ERR-046).
- O agendador usa o dia civil de `America/Sao_Paulo` pelo relógio injetado, marca o dia ao iniciar a execução e tem guarda de reentrada (CA-070, ADR-004).
- Não achei dependência nova, supressão de alerta (`nosemgrep`, `eslint-disable`, `@ts-ignore`, `gitleaks:allow`) nem atalho para passar nos testes.
- Na evidência GREEN, os 762 testes passaram, e SAST, gitleaks, `npm audit`, consistência, contrato e mutação estão verdes.

Limitação: o DIFF_DA_TAREFA foi cortado em 40000 caracteres. Por isso, revisei os arquivos de código direto no repositório, mas não consegui conferir pelo diff se `package.json` e os testes aprovados ficaram intactos.

VEREDITO: BLOQUEADO
