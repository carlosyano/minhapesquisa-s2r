// Job diário de limpeza dos arquivos que sobraram de importações terminadas (RF-016, RN-053 a
// RN-055, CA-064 a CA-069, ERR-046; CHG-020, DEC-237, F-21 do PLANO §12.3, IMP-011).
//
// O job roda no ciclo de manutenção do harness (clock.advance / worker.processar), uma vez por
// dia civil de America/Sao_Paulo, como o expurgo da DEC-069 roda no worker da exportação; o
// contrato completo está em tests/support/limpeza.ts. O resto é plantado com o seed que regrava
// a página na pasta (a exclusão do worker que falhou); o worker já deixou chave_storage NULL
// (RN-054 (3)). Modelos em branco e bytes fixos, sem dado pessoal (DEC-133, Q-001).
//
// A lista de estados que o job apaga é fechada (RN-053 (3)): o banco só aceita os cinco estados
// do FL-004 (ck_importacao_estado), e os três não finais são provados no CA-065; um estado novo
// ou inesperado nunca entraria no filtro `estado IN ('concluida','falhou')`.

import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { randomUUID } from 'node:crypto';
import { avancarAte, auditoriaLimpeza, chavePaginaDe, contagensExecucao, execucoes, falharApagar, desfalharApagar, importacaoTerminada, logsDesde, marcaLogs, pastaDe, pastaSemRegistro, plantarObjeto, plantarResto, semVazamento, virarDiaCivil } from '../../support/limpeza.js';
import { entrar, tenantComUsuaria } from '../../support/cenarios.js';
import { projetoCriado } from '../../support/formularios.js';
import { criarHarness, type Harness } from '../../support/harness.js';
import { consultarImportacao, importar, lida, modeloPdf } from '../../support/importacao.js';
import { prepararCotacao } from '../../support/leitura.js';
import type { Cliente } from '../../support/cliente.js';
import type { TenantPronto } from '../../support/cenarios.js';

let h: Harness;
let T: TenantPronto;
let c: Cliente;
let projeto: string;

beforeAll(async () => {
  h = await criarHarness();
  // Só o mês de novembro tem cotação: o exemplo 2 do CA-065 fica parado na virada para
  // dezembro (mês sem cotação, FL-004), como uma importação que espera há dias.
  await prepararCotacao(h, ['2026-11-01']);
  T = await tenantComUsuaria(h, 'Tenant A limpeza');
  c = await entrar(h, T.usuaria);
  projeto = await projetoCriado(c, 'Saúde 60+');
});
afterAll(async () => {
  await h?.close();
});

describe('CA-064 — o job apaga o resto das importações terminadas', () => {
  // @trace CA-064, RF-016, RN-053, RN-054, FL-004, DEC-237
  it('CA-064 exemplos 1 a 3: concluida e falhou ficam sem arquivo, chave_storage NULL, estado e formulário intactos', async () => {
    // Exemplo 1: "Hábitos" concluida com 1.jpg. Exemplo 2: "Idosos" falhou com 1.jpg e 2.jpg
    // (a exclusão falhou depois da página 1). Exemplo 3: concluida do tenant "B", limpa pela própria pasta.
    const habitos = await importacaoTerminada(h, c, projeto, { nome: 'Hábitos', paginas: 1, estado: 'concluida' });
    const idosos = await importacaoTerminada(h, c, projeto, { nome: 'Idosos', paginas: 2, estado: 'falhou' });
    const B = await tenantComUsuaria(h, 'Tenant B limpeza');
    const cB = await entrar(h, B.usuaria);
    const projetoB = await projetoCriado(cB, 'Saúde 60+ B');
    const doB = await importacaoTerminada(h, cB, projetoB, { nome: 'Modelo B', paginas: 1, estado: 'concluida' });

    // O worker já apagou as tarefas e deixou chave_storage NULL; o resto plantado coexiste com NULL.
    for (const [imp, paginas] of [[habitos, 1], [idosos, 2], [doB, 1]] as const) {
      expect(await h.inspect.importacao(imp.id)).toMatchObject({ chave_storage: null, objetos: 0, tarefas: [] });
      await plantarResto(h, imp.id, Array.from({ length: paginas }, (_, i) => i + 1));
    }
    const antesA = [(await consultarImportacao(c, habitos.id)).corpo, (await consultarImportacao(c, idosos.id)).corpo];
    const antesB = (await consultarImportacao(cB, doB.id)).corpo;

    const marca = await marcaLogs(h);
    await virarDiaCivil(h);

    // A virada do dia encerra as sessões ociosas; um novo login segue o teste.
    const cA2 = await entrar(h, T.usuaria);
    const cB2 = await entrar(h, B.usuaria);
    expect((await consultarImportacao(cA2, habitos.id)).corpo).toEqual(antesA[0]);
    expect((await consultarImportacao(cA2, idosos.id)).corpo).toEqual(antesA[1]);
    expect((await consultarImportacao(cB2, doB.id)).corpo).toEqual(antesB);
    expect(await h.inspect.importacao(habitos.id)).toMatchObject({ estado: 'concluida', chave_storage: null, objetos: 0 });
    expect(await h.inspect.importacao(idosos.id)).toMatchObject({ estado: 'falhou', chave_storage: null, objetos: 0 });
    expect(await h.inspect.importacao(doB.id)).toMatchObject({ estado: 'concluida', chave_storage: null, objetos: 0 });

    for (const [tenant, imp] of [[T.tenantId, habitos], [T.tenantId, idosos], [B.tenantId, doB]] as const) {
      expect(await auditoriaLimpeza(h, tenant, imp.id)).toHaveLength(1);
    }
    const novos = await logsDesde(h, marca);
    const resumos = contagensExecucao(novos);
    expect(resumos).toHaveLength(1);
    expect(resumos[0].apagados).toBe(4); // 1 + 2 + 1
    expect(resumos[0].falhas).toBe(0);
    expect(resumos[0].verificadas).toBeGreaterThanOrEqual(3);
    semVazamento(JSON.stringify(await auditoriaLimpeza(h, T.tenantId)) + JSON.stringify(await auditoriaLimpeza(h, B.tenantId)) + novos, ['Hábitos', 'Idosos', 'Modelo B']);
  });
});

describe('CA-066 — o job só apaga a pasta da importação', () => {
  // @trace CA-066, RF-016, RN-054, RN-053, DEC-237
  it('CA-066 aplicação, exportação, pasta sem registro e arquivos de outro tenant continuam presentes', async () => {
    c = await entrar(h, T.usuaria);
    const imp = await importacaoTerminada(h, c, projeto, { nome: 'Hábitos isolado', paginas: 1, estado: 'concluida' });
    await plantarResto(h, imp.id, [1]);

    // Arquivos de aplicação e de exportação do tenant A, pasta de importação sem registro no
    // banco, e os próprios arquivos do tenant B (aplicação, exportação e pasta sem registro).
    const B = await tenantComUsuaria(h, 'Tenant B isolamento');
    const aplicacaoA = `tenant/${T.tenantId}/aplicacao/${randomUUID()}/${randomUUID()}.jpg`;
    const exportacaoA = `tenant/${T.tenantId}/exportacao/${randomUUID()}.csv`;
    const orfaA = pastaSemRegistro(T.tenantId);
    const aplicacaoB = `tenant/${B.tenantId}/aplicacao/${randomUUID()}/${randomUUID()}.jpg`;
    const exportacaoB = `tenant/${B.tenantId}/exportacao/${randomUUID()}.xlsx`;
    const orfaB = pastaSemRegistro(B.tenantId);
    for (const chave of [aplicacaoA, exportacaoA, orfaA.chave, aplicacaoB, exportacaoB, orfaB.chave]) await plantarObjeto(chave);

    expect((await h.inspect.contagemUpload(T.tenantId)).objetos).toBe(4); // resto + aplicação + exportação + órfã
    expect((await h.inspect.contagemImportacao(T.tenantId)).objetos).toBe(2); // resto + órfã
    expect((await h.inspect.contagemUpload(B.tenantId)).objetos).toBe(3);

    const marca = await marcaLogs(h);
    await virarDiaCivil(h);

    expect(await h.inspect.importacao(imp.id)).toMatchObject({ estado: 'concluida', chave_storage: null, objetos: 0 });
    expect((await h.inspect.contagemUpload(T.tenantId)).objetos).toBe(3); // aplicação + exportação + órfã
    expect((await h.inspect.contagemImportacao(T.tenantId)).objetos).toBe(1); // só a órfã
    expect((await h.inspect.contagemUpload(B.tenantId)).objetos).toBe(3);
    expect((await h.inspect.contagemImportacao(B.tenantId)).objetos).toBe(1);
    expect(await auditoriaLimpeza(h, T.tenantId, imp.id)).toHaveLength(1);
    expect(await auditoriaLimpeza(h, T.tenantId, orfaA.id)).toEqual([]);
    expect(await auditoriaLimpeza(h, B.tenantId)).toEqual([]);

    const resumos = contagensExecucao(await logsDesde(h, marca));
    expect(resumos).toHaveLength(1);
    expect(resumos[0].apagados).toBe(1);
    expect(resumos[0].falhas).toBe(0);
  });
});

describe('CA-067 — o job pode rodar de novo sem erro', () => {
  // @trace CA-067, RF-016, RN-053, RN-055, DEC-237
  it('CA-067 a segunda execução termina sem erro, sem apagar nada e sem auditar importação', async () => {
    c = await entrar(h, T.usuaria);
    const imp = await importacaoTerminada(h, c, projeto, { nome: 'Hábitos reaplicável', paginas: 1, estado: 'concluida' });
    await plantarResto(h, imp.id, [1]);
    const orfa = pastaSemRegistro(T.tenantId);
    const aplicacao = `tenant/${T.tenantId}/aplicacao/${randomUUID()}/${randomUUID()}.jpg`;
    await plantarObjeto(orfa.chave);
    await plantarObjeto(aplicacao);

    await virarDiaCivil(h);
    expect(await h.inspect.importacao(imp.id)).toMatchObject({ chave_storage: null, objetos: 0 });
    expect(await auditoriaLimpeza(h, T.tenantId, imp.id)).toHaveLength(1);
    const objetosA = (await h.inspect.contagemUpload(T.tenantId)).objetos;

    // A pasta da importação terminada não existe mais (nenhum objeto com o prefixo); rodar de
    // novo em seguida não dá erro, não apaga nada e não audita.
    const marca = await marcaLogs(h);
    await virarDiaCivil(h);
    const resumos = contagensExecucao(await logsDesde(h, marca));
    expect(resumos).toHaveLength(1);
    expect(resumos[0].apagados).toBe(0);
    expect(resumos[0].falhas).toBe(0);
    expect(resumos[0].verificadas).toBeGreaterThanOrEqual(1);
    expect(await auditoriaLimpeza(h, T.tenantId, imp.id)).toHaveLength(1);
    expect(await h.inspect.importacao(imp.id)).toMatchObject({ estado: 'concluida', chave_storage: null, objetos: 0 });
    expect((await h.inspect.contagemUpload(T.tenantId)).objetos).toBe(objetosA);
  });
});

describe('CA-069 — log e auditoria só com identificadores e contagens', () => {
  // @trace CA-069, RF-016, RN-055, RN-028, DEC-237
  it('CA-069 auditoria LIMPEZA_IMPORTACAO com apagados 2 e restantes 0; log da execução só com contagens', async () => {
    c = await entrar(h, T.usuaria);
    const imp = await importacaoTerminada(h, c, projeto, { nome: 'Hábitos auditado', paginas: 2, estado: 'concluida' });
    await plantarResto(h, imp.id, [1, 2]);

    const marca = await marcaLogs(h);
    await virarDiaCivil(h);

    const eventos = await auditoriaLimpeza(h, T.tenantId, imp.id);
    expect(eventos).toHaveLength(1);
    expect(eventos[0]).toMatchObject({
      tenant_id: T.tenantId,
      usuario_id: null, // ator de sistema
      acao: 'LIMPEZA_IMPORTACAO',
      entidade: 'ImportacaoFormulario',
      registro_id: imp.id,
      campo: null,
    });
    expect(eventos[0].detalhes).toEqual({ apagados: 2, restantes: 0 });

    const novos = await logsDesde(h, marca);
    expect(execucoes(novos)).toHaveLength(1); // um único log por execução (RN-055 (3))
    const resumos = contagensExecucao(novos);
    expect(resumos[0].apagados).toBe(2);
    expect(resumos[0].falhas).toBe(0);
    // Nem a auditoria nem o log têm nome de arquivo, caminho, conteúdo ou mensagem do sistema.
    semVazamento(JSON.stringify(eventos) + novos, ['Hábitos auditado', '1.jpg', '2.jpg']);
  });
});

describe('CA-068 e ERR-046 — a falha de uma importação não interrompe as demais', () => {
  // @trace CA-068, ERR-046, RF-016, RN-053, RN-055, RN-028, DEC-237
  it('CA-068 armazenamento falha em "Hábitos" (A): "Idosos" (B) e as demais de A são limpas; retry no dia seguinte', async () => {
    c = await entrar(h, T.usuaria);
    const habitos = await importacaoTerminada(h, c, projeto, { nome: 'Hábitos com falha', paginas: 1, estado: 'concluida' });
    const extra = await importacaoTerminada(h, c, projeto, { nome: 'Extra de A', paginas: 1, estado: 'concluida' });
    const B = await tenantComUsuaria(h, 'Tenant B falha');
    const cB = await entrar(h, B.usuaria);
    const projetoB = await projetoCriado(cB, 'Saúde 60+ B');
    const idosos = await importacaoTerminada(h, cB, projetoB, { nome: 'Idosos', paginas: 1, estado: 'concluida' });
    await plantarResto(h, habitos.id, [1]);
    await plantarResto(h, extra.id, [1]);
    await plantarResto(h, idosos.id, [1]);

    const chave = chavePaginaDe(T.tenantId, habitos.id, 1);
    const mensagem = `EACCES: permission denied, unlink '${chave}'`;
    await falharApagar(pastaDe(T.tenantId, habitos.id), { nome: 'ErroArmazenamento', mensagem });

    const marca = await marcaLogs(h);
    await virarDiaCivil(h);

    // A falha de uma importação não interrompe as demais do mesmo tenant nem as de outro tenant.
    expect(await h.inspect.importacao(habitos.id)).toMatchObject({ estado: 'concluida', objetos: 1 });
    expect(await h.inspect.importacao(extra.id)).toMatchObject({ estado: 'concluida', chave_storage: null, objetos: 0 });
    expect(await h.inspect.importacao(idosos.id)).toMatchObject({ estado: 'concluida', chave_storage: null, objetos: 0 });

    const novos = await logsDesde(h, marca);
    const resumos = contagensExecucao(novos);
    expect(resumos).toHaveLength(1);
    expect(resumos[0].apagados).toBe(2);
    expect(resumos[0].falhas).toBe(1);
    // ERR-046: log de erro só com identificadores, contagens e o nome da classe do erro.
    expect(novos).toContain('import_cleanup_failed');
    expect(novos).toContain(`tenant_id=${T.tenantId}`);
    expect(novos).toContain(`importacao_id=${habitos.id}`);
    expect(novos).toContain('erro=ErroArmazenamento');
    const eventos = await auditoriaLimpeza(h, T.tenantId, habitos.id);
    expect(eventos).toHaveLength(1);
    expect(eventos[0].detalhes).toEqual({ apagados: 0, restantes: 1, falha: true, erro: 'ErroArmazenamento' });
    expect(eventos[0].usuario_id).toBeNull();
    semVazamento(JSON.stringify(eventos) + novos, [mensagem, 'EACCES', 'permission', 'unlink', 'Hábitos com falha']);

    // O que falhou é tentado de novo na execução do dia seguinte, e aí é limpo.
    await desfalharApagar(pastaDe(T.tenantId, habitos.id));
    const marca2 = await marcaLogs(h);
    await virarDiaCivil(h);
    expect(await h.inspect.importacao(habitos.id)).toMatchObject({ estado: 'concluida', chave_storage: null, objetos: 0 });
    const eventos2 = await auditoriaLimpeza(h, T.tenantId, habitos.id);
    expect(eventos2).toHaveLength(2);
    expect(eventos2[1].detalhes).toEqual({ apagados: 1, restantes: 0 });
    const resumos2 = contagensExecucao(await logsDesde(h, marca2));
    expect(resumos2).toHaveLength(1);
    expect(resumos2[0].apagados).toBe(1);
    expect(resumos2[0].falhas).toBe(0);
  });

  // @trace ERR-046, CA-068, RF-016, RN-055, RN-028
  it('ERR-046 falha parcial: a página 1 é apagada, a 2 resta; auditoria e log registram a falha sem caminho nem mensagem', async () => {
    c = await entrar(h, T.usuaria);
    const imp = await importacaoTerminada(h, c, projeto, { nome: 'Hábitos parcial', paginas: 2, estado: 'concluida' });
    await plantarResto(h, imp.id, [1, 2]);
    // Sem nome nem mensagem personalizados: o padrão do gancho traz o caminho e o nome do
    // arquivo, como um erro real do sistema de arquivos, e não pode aparecer no registro.
    await falharApagar(chavePaginaDe(T.tenantId, imp.id, 2));

    const marca = await marcaLogs(h);
    await virarDiaCivil(h);

    expect(await h.inspect.importacao(imp.id)).toMatchObject({ estado: 'concluida', objetos: 1 });
    const eventos = await auditoriaLimpeza(h, T.tenantId, imp.id);
    expect(eventos).toHaveLength(1);
    expect(eventos[0].detalhes).toEqual({ apagados: 1, restantes: 1, falha: true, erro: 'ErroArmazenamento' });
    const novos = await logsDesde(h, marca);
    expect(novos).toContain('import_cleanup_failed');
    expect(novos).toContain('erro=ErroArmazenamento');
    const resumos = contagensExecucao(novos);
    expect(resumos).toHaveLength(1);
    expect(resumos[0].apagados).toBe(1);
    expect(resumos[0].falhas).toBe(1);
    semVazamento(JSON.stringify(eventos) + novos, ['falha simulada ao apagar', 'Hábitos parcial']);

    await desfalharApagar();
    await virarDiaCivil(h);
    expect(await h.inspect.importacao(imp.id)).toMatchObject({ chave_storage: null, objetos: 0 });
  });
});

describe('CA-065 — o job nunca apaga importação em andamento', () => {
  // @trace CA-065, RF-016, RN-053, RN-054, FL-004, DEC-237
  it('CA-065 exemplo 1: enfileirada com 1.jpg continua com o arquivo e sem auditoria de limpeza', async () => {
    c = await entrar(h, T.usuaria);
    const r = await importar(c, projeto, [await modeloPdf(1)], { nome: 'Hábitos enfileirada' });
    expect(r.status, r.texto).toBe(202);
    const id = r.corpo.id;
    // A página falha nas duas primeiras chamadas: no ciclo do job o worker ainda não terminou
    // a importação (a 3ª tentativa fica para depois), como uma importação recém-enfileirada.
    h.extrator.programar(id, { 1: { falha: { tipo: 'erro', vezes: 2 } } });
    expect(await h.inspect.importacao(id)).toMatchObject({ estado: 'enfileirada', objetos: 1 });
    const chaveAntes = (await h.inspect.importacao(id)).chave_storage;
    expect(chaveAntes).toBe(pastaDe(T.tenantId, id));

    const marca = await marcaLogs(h);
    await virarDiaCivil(h);

    // O job executou no ciclo e não tocou a importação não final: arquivo presente,
    // chave_storage intacto, estado não final e nenhuma auditoria de limpeza.
    expect(contagensExecucao(await logsDesde(h, marca))).toHaveLength(1);
    const gravada = await h.inspect.importacao(id);
    expect(gravada.objetos).toBe(1);
    expect(gravada.chave_storage).toBe(chaveAntes);
    expect(['enfileirada', 'em_andamento']).toContain(gravada.estado);
    expect(await auditoriaLimpeza(h, T.tenantId, id)).toEqual([]);
  });

  // @trace CA-065, RF-016, RN-053, FL-004, DEC-237
  it('CA-065 exemplo 3: em_andamento com as páginas na pasta continua intacta', async () => {
    c = await entrar(h, T.usuaria);
    const r = await importar(c, projeto, [await modeloPdf(2)], { nome: 'Hábitos em andamento' });
    expect(r.status, r.texto).toBe(202);
    const id = r.corpo.id;
    h.extrator.programar(id, {
      1: { perguntas: [lida('Você dorme bem?', 'sim_nao')] },
      2: { falha: { tipo: 'tempo_esgotado', vezes: 2 } },
    });
    await h.worker.processar(); // página 1 lida; página 2 falha a 1ª chamada e espera a retentativa
    expect(await h.inspect.importacao(id)).toMatchObject({ estado: 'em_andamento', objetos: 2 });
    const chaveAntes = (await h.inspect.importacao(id)).chave_storage;

    const marca = await marcaLogs(h);
    await virarDiaCivil(h); // a 2ª chamada da página 2 também falha; a 3ª fica para depois

    expect(contagensExecucao(await logsDesde(h, marca))).toHaveLength(1);
    const gravada = await h.inspect.importacao(id);
    expect(gravada).toMatchObject({ estado: 'em_andamento', objetos: 2 });
    expect(gravada.chave_storage).toBe(chaveAntes);
    expect(await auditoriaLimpeza(h, T.tenantId, id)).toEqual([]);
  });

  // @trace CA-065, RF-016, RN-053, RN-036, FL-004, DEC-237
  it('CA-065 exemplo 2: aguardando_cota parada desde o mês anterior continua intacta na virada do mês', async () => {
    const t = await tenantComUsuaria(h, 'Tenant cota limpeza');
    const u = await entrar(h, t.usuaria);
    const idProjeto = await projetoCriado(u, 'Saúde 60+ cota');
    await h.seed.parametro({ tenantId: t.tenantId, chave: 'custo_ia_teto', valor: '500.00' });
    await h.seed.consumoIa({ tenantId: t.tenantId, valorReais: '500.00' });
    const r = await importar(u, idProjeto, [await modeloPdf(1)], { nome: 'Hábitos sem cota' });
    expect(r.status, r.texto).toBe(202);
    const id = r.corpo.id;
    h.extrator.programar(id, { 1: { perguntas: [lida('Você dorme bem?', 'sim_nao')] } });
    await h.worker.processar();
    expect(await h.inspect.importacao(id)).toMatchObject({ estado: 'aguardando_cota', objetos: 1 });
    const chaveAntes = (await h.inspect.importacao(id)).chave_storage;
    const criadaEm = new Date(r.corpo.criada_em);

    // Dias parada, até a virada do mês: o job roda em cada dia civil e não toca a importação.
    const marca = await marcaLogs(h);
    await avancarAte(h, new Date('2026-12-01T03:00:00Z')); // meia-noite civil de 01/12 em America/Sao_Paulo
    await h.worker.processar(); // a retomada da cota não libera: dezembro não tem cotação (FL-004)
    expect(contagensExecucao(await logsDesde(h, marca)).length).toBeGreaterThanOrEqual(1);
    expect(h.clock.now().getUTCMonth()).toBe(11);
    expect(criadaEm.getUTCMonth()).toBe(10);

    const gravada = await h.inspect.importacao(id);
    expect(gravada).toMatchObject({ estado: 'aguardando_cota', objetos: 1 });
    expect(gravada.chave_storage).toBe(chaveAntes);
    expect(await auditoriaLimpeza(h, t.tenantId, id)).toEqual([]);
    const u2 = await entrar(h, t.usuaria);
    expect((await consultarImportacao(u2, id)).corpo).toMatchObject({ estado: 'aguardando_cota', aviso: 'ERR-003' });
  });
});
