// Apoio ao job diário de limpeza dos arquivos de importação (IA-TEST do IMP-011: RF-016,
// RN-053 a RN-055, CA-064 a CA-070, ERR-046; CHG-020, DEC-237, F-21 do PLANO §12.3).
// Dados 100% sintéticos (Q-001, DEC-133): os "restos" são bytes fixos, nunca dado pessoal.
//
// Contrato para o IA-DEV (o test-harness é protegido; nada aqui exige mudá-lo):
//
// 1. O ciclo de manutenção no harness é o ciclo do worker: `clock.advance` (rodarJobs →
//    worker.executarVencidas) e `worker.processar`. O AgendadorDiario deve ser chamado nesse
//    ciclo, como o expurgo da exportação já roda no WorkerExportacao.executarVencidas (DEC-069).
//    Ele executa o job uma vez por dia civil de `n.agora()` em America/Sao_Paulo (UTC-3), marca
//    o dia ao iniciar a execução e tem guarda de reentrada (ADR-004 do DESIGN). Reiniciar o
//    processo = criar um harness novo: o último dia fica só em memória.
//
// 2. O job gera um único log por execução, só com contagens (RN-055 (3), ADR-005):
//      limpeza_importacao_execucao verificadas=<n> apagados=<n> falhas=<n>
//    e, por importação que falhou, o log de erro (ERR-046, código IMPORT_CLEANUP_FAILED):
//      import_cleanup_failed tenant_id=<uuid> importacao_id=<uuid> apagados=<n> restantes=<n> erro=<NomeDaClasse>
//    Auditoria por importação com resto: ação LIMPEZA_IMPORTACAO, entidade ImportacaoFormulario,
//    registro_id = id da importação, ator de sistema (usuario_id NULL), detalhes
//    { apagados, restantes } no sucesso e { apagados, restantes, falha: true, erro: <NomeDaClasse> }
//    na falha. Importação sem resto não é auditada (RN-055 (2)).
//
// 3. `@minhapesquisa/api` (index.ts) passa a exportar, sobre o ArmazenamentoEmMemoria mais
//    recente iniciado (o armazenamento do harness ativo), três funções de teste:
//      plantarObjeto(chave: string, conteudo?: string): Promise<void>
//        grava bytes sintéticos na chave dada (padrão 'objeto sintético de teste'), como um
//        arquivo que sobrou de outra operação; não toca o banco.
//      falharApagar(prefixo: string, opts?: { nome?: string; mensagem?: string }): void
//        todo `apagar(chave)` com chave.startsWith(prefixo) rejeita com um Error de nome
//        opts.nome ?? 'ErroArmazenamento' e mensagem opts.mensagem ?? `falha simulada ao apagar ${chave}`
//        (a mensagem padrão traz o caminho e o nome do arquivo, como um erro real do sistema
//        de arquivos; RN-028 proíbe registrá-la). Vale até desfalharApagar.
//      desfalharApagar(prefixo?: string): void
//        remove a falha simulada do prefixo (ou todas, sem prefixo).
//    O ArmazenamentoEmMemoria é só de teste (infra/armazenamento.ts); o registro das instâncias
//    e das falhas vive nele, e o index.ts só reexporta as funções.
//
// 4. O resto de uma importação terminada é plantado com o `seed.corromperPaginaImportacao` que
//    já existe: ele regrava o arquivo da página na pasta da importação, como uma exclusão do
//    worker que falhou (PLANO §4.8). O worker já deixou `chave_storage` NULL antes de excluir
//    (RN-054 (3)); o seed não o muda, e o job tem de achar o resto mesmo assim.

import { randomUUID } from 'node:crypto';
import { expect } from 'vitest';
import type { Cliente } from './cliente.js';
import { projetoCriado } from './formularios.js';
import type { EventoAuditoria, Harness, RoteiroImportacao } from './harness.js';
import { lida, modeloPdf, importarEProcessar } from './importacao.js';
import { DIA, HORA, entrar, tenantComUsuaria, type TenantPronto } from './cenarios.js';

export { DIA, HORA };

/** Pasta e chave da página, como o PLANO §4.8 e a RN-054 as definem (montadas só com ids do banco). */
export const pastaDe = (tenantId: string, importacaoId: string) => `tenant/${tenantId}/importacao/${importacaoId}/`;
export const chavePaginaDe = (tenantId: string, importacaoId: string, pagina: number) => `${pastaDe(tenantId, importacaoId)}${pagina}.jpg`;

/** Bytes fixos que o seed.corromperPaginaImportacao grava; conteúdo que nunca pode aparecer no log (RN-028). */
export const CONTEUDO_RESTO = 'arquivo corrompido';

/** O que nunca aparece no log nem na auditoria do job (RN-028, CA-069): nomes, caminhos e conteúdo. */
export const PROIBIDOS_RN028 = ['.jpg', 'tenant/', 'importacao/', CONTEUDO_RESTO];

/** Confere que o texto (log, auditoria serializada) não traz nada proibido, mais os extras do teste. */
export function semVazamento(texto: string, extras: string[] = []): void {
  for (const proibido of [...PROIBIDOS_RN028, ...extras]) expect(texto).not.toContain(proibido);
}

/** Regrava as páginas na pasta da importação terminada, como a exclusão do worker que falhou. */
export async function plantarResto(h: Harness, importacaoId: string, paginas: number[]): Promise<void> {
  for (const p of paginas) await h.seed.corromperPaginaImportacao(importacaoId, p);
  const gravada = await h.inspect.importacao(importacaoId);
  expect(gravada.objetos).toBe(paginas.length);
}

/** Importação terminada pela API, com o extrator simulado; `falhou` não lê nenhuma pergunta (ERR-044). */
export async function importacaoTerminada(
  h: Harness,
  c: Cliente,
  projetoId: string,
  opts: { nome: string; paginas: number; estado: 'concluida' | 'falhou' },
): Promise<any> {
  const roteiro: RoteiroImportacao = { 1: { perguntas: [] } };
  if (opts.estado === 'concluida') {
    for (let p = 1; p <= opts.paginas; p++) roteiro[p] = { perguntas: [lida('Você dorme bem?', 'sim_nao')] };
  }
  const imp = await importarEProcessar(h, c, projetoId, roteiro, [await modeloPdf(opts.paginas)], opts.nome);
  expect(imp.estado, imp.aviso ?? '').toBe(opts.estado);
  expect(imp.total_paginas).toBe(opts.paginas);
  return imp;
}

/** Tenant novo com usuária, projeto e uma importação terminada com resto plantado na pasta. */
export async function tenantComResto(
  h: Harness,
  nome: string,
  opts: { nomeFormulario: string; paginas: number; estado: 'concluida' | 'falhou' },
): Promise<{ t: TenantPronto; c: Cliente; projeto: string; imp: any }> {
  const t = await tenantComUsuaria(h, nome);
  const c = await entrar(h, t.usuaria);
  const projeto = await projetoCriado(c, 'Saúde 60+');
  const imp = await importacaoTerminada(h, c, projeto, { nome: opts.nomeFormulario, paginas: opts.paginas, estado: opts.estado });
  await plantarResto(h, imp.id, Array.from({ length: opts.paginas }, (_, i) => i + 1));
  return { t, c, projeto, imp };
}

/** Comprimento do log atual: tudo o que vier depois dele é da operação em teste. */
export async function marcaLogs(h: Harness): Promise<number> {
  return (await h.inspect.logs()).length;
}

export async function logsDesde(h: Harness, marca: number): Promise<string> {
  return (await h.inspect.logs()).slice(marca);
}

/** Linhas do log da execução do job (RN-055 (3)); uma por execução. */
export function execucoes(logs: string): string[] {
  return logs.match(/^limpeza_importacao_execucao .*$/gm) ?? [];
}

/** Contagens de cada execução; o formato fechado (só identificadores e contagens) é conferido aqui. */
export function contagensExecucao(logs: string): { verificadas: number; apagados: number; falhas: number }[] {
  return execucoes(logs).map((linha) => {
    const m = linha.match(/^limpeza_importacao_execucao verificadas=(\d+) apagados=(\d+) falhas=(\d+)$/);
    if (!m) throw new Error(`log de execução fora do formato da RN-055 (3): ${linha}`);
    return { verificadas: Number(m[1]), apagados: Number(m[2]), falhas: Number(m[3]) };
  });
}

/** Eventos LIMPEZA_IMPORTACAO do tenant, opcionalmente só os de uma importação. */
export async function auditoriaLimpeza(h: Harness, tenantId: string, importacaoId?: string): Promise<EventoAuditoria[]> {
  const eventos = await h.inspect.auditoria(tenantId);
  return eventos.filter((e) => e.acao === 'LIMPEZA_IMPORTACAO' && (importacaoId === undefined || e.registro_id === importacaoId));
}

/**
 * Avança o relógio até a próxima meia-noite civil de America/Sao_Paulo (UTC-3, sem horário de
 * verão): o primeiro ciclo do dia seguinte, em que o agendador deve executar o job (CA-070).
 */
export async function virarDiaCivil(h: Harness): Promise<void> {
  const agora = h.clock.now();
  const alvo = new Date(agora);
  alvo.setUTCHours(3, 0, 0, 0);
  if (alvo.getTime() <= agora.getTime()) alvo.setUTCDate(alvo.getUTCDate() + 1);
  await h.clock.advance(alvo.getTime() - agora.getTime());
}

/** Avança o relógio até o instante dado (que deve estar no futuro). */
export async function avancarAte(h: Harness, alvo: Date): Promise<void> {
  const ms = alvo.getTime() - h.clock.now().getTime();
  expect(ms).toBeGreaterThan(0);
  await h.clock.advance(ms);
}

/** Pasta de importação sem registro no banco, plantada no armazenamento (CA-066, RN-054 (2)). */
export function pastaSemRegistro(tenantId: string): { id: string; pasta: string; chave: string } {
  const id = randomUUID();
  const pasta = pastaDe(tenantId, id);
  return { id, pasta, chave: `${pasta}1.jpg` };
}

// ─────────────────────────── ganchos de teste no armazenamento ───────────────────────────
// Import dinâmico: no RED o módulo ainda não exporta as funções, e cada teste falha com a
// mensagem do contrato, em vez de o arquivo inteiro falhar na coleta.

async function ganchos(): Promise<Record<string, any>> {
  return (await import('@minhapesquisa/api')) as unknown as Record<string, any>;
}

const CONTRATO = 'IA-TEST: @minhapesquisa/api deve exportar o gancho de teste sobre o ArmazenamentoEmMemoria do harness (RF-016, ERR-046; ver tests/support/limpeza.ts)';

/** Grava um objeto sintético na chave dada, no armazenamento do harness ativo. */
export async function plantarObjeto(chave: string, conteudo?: string): Promise<void> {
  const api = await ganchos();
  if (typeof api.plantarObjeto !== 'function') throw new Error(`${CONTRATO}: plantarObjeto(chave, conteudo?)`);
  await api.plantarObjeto(chave, conteudo);
}

/** Faz o `apagar` rejeitar para as chaves com o prefixo, até desfalharApagar (CA-068, ERR-046). */
export async function falharApagar(prefixo: string, opts: { nome?: string; mensagem?: string } = {}): Promise<void> {
  const api = await ganchos();
  if (typeof api.falharApagar !== 'function') throw new Error(`${CONTRATO}: falharApagar(prefixo, opts?)`);
  api.falharApagar(prefixo, opts);
}

/** Remove a falha simulada do prefixo (ou todas, sem prefixo). */
export async function desfalharApagar(prefixo?: string): Promise<void> {
  const api = await ganchos();
  if (typeof api.desfalharApagar !== 'function') throw new Error(`${CONTRATO}: desfalharApagar(prefixo?)`);
  api.desfalharApagar(prefixo);
}
