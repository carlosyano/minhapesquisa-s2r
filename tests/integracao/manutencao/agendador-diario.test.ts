// Agendador do job diário de limpeza (CA-070, RF-016, RN-053, RN-055; CHG-020, DEC-237,
// ADR-004 do DESIGN). O ciclo do processo de manutenção é o ciclo do worker no harness
// (clock.advance / worker.processar): o job executa uma vez no primeiro ciclo de cada dia
// civil de America/Sao_Paulo, sem intervenção da usuária, e o último dia fica só em memória —
// reiniciar o processo (um harness novo) executa no primeiro ciclo de novo; rodar a mais não
// causa dano (CA-067). O contrato completo está em tests/support/limpeza.ts.

import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { auditoriaLimpeza, contagensExecucao, importacaoTerminada, logsDesde, marcaLogs, plantarResto, virarDiaCivil } from '../../support/limpeza.js';
import { HORA, MINUTO, entrar, tenantComUsuaria, type TenantPronto } from '../../support/cenarios.js';
import { projetoCriado } from '../../support/formularios.js';
import { criarHarness, type Harness } from '../../support/harness.js';
import { prepararCotacao } from '../../support/leitura.js';
import type { Cliente } from '../../support/cliente.js';

let h1: Harness;
let T1: TenantPronto;
let c1: Cliente;
let projeto1: string;
let imp1: any;

beforeAll(async () => {
  h1 = await criarHarness();
  await prepararCotacao(h1);
  T1 = await tenantComUsuaria(h1, 'Tenant agendador');
  c1 = await entrar(h1, T1.usuaria);
  projeto1 = await projetoCriado(c1, 'Saúde 60+');
  imp1 = await importacaoTerminada(h1, c1, projeto1, { nome: 'Hábitos do dia', paginas: 1, estado: 'concluida' });
  await plantarResto(h1, imp1.id, [1]);
  // Primeiro ciclo do processo no dia civil de início (02/11/2026): o job executa, com resto
  // ou sem ele; o dia fica marcado em memória.
  await h1.clock.advance(MINUTO);
});
afterAll(async () => {
  await h1?.close();
});

describe('CA-070 — o job roda uma vez por dia, sozinho', () => {
  // @trace CA-070, RF-016, RN-053, RN-055, DEC-237
  it('CA-070 executa no primeiro ciclo de cada dia civil e não executa nos outros ciclos do mesmo dia', async () => {
    const marca = await marcaLogs(h1);
    await virarDiaCivil(h1);
    let resumos = contagensExecucao(await logsDesde(h1, marca));
    expect(resumos).toHaveLength(1);
    expect(resumos[0].falhas).toBe(0);
    expect(await h1.inspect.importacao(imp1.id)).toMatchObject({ estado: 'concluida', chave_storage: null, objetos: 0 });

    // Resto novo no mesmo dia: os ciclos seguintes não executam o job e o arquivo continua.
    c1 = await entrar(h1, T1.usuaria);
    const imp2 = await importacaoTerminada(h1, c1, projeto1, { nome: 'Modelo do mesmo dia', paginas: 1, estado: 'concluida' });
    await plantarResto(h1, imp2.id, [1]);
    await h1.clock.advance(HORA);
    await h1.clock.advance(2 * HORA);
    expect(contagensExecucao(await logsDesde(h1, marca))).toHaveLength(1);
    expect(await h1.inspect.importacao(imp2.id)).toMatchObject({ estado: 'concluida', objetos: 1 });

    // Começa o dia seguinte: executa uma vez, no primeiro ciclo, e limpa o resto.
    await virarDiaCivil(h1);
    resumos = contagensExecucao(await logsDesde(h1, marca));
    expect(resumos).toHaveLength(2);
    expect(resumos[1].apagados).toBe(1);
    expect(resumos[1].falhas).toBe(0);
    expect(await h1.inspect.importacao(imp2.id)).toMatchObject({ chave_storage: null, objetos: 0 });

    // Os outros ciclos do mesmo dia não executam: um resto novo fica para o dia seguinte.
    await h1.clock.advance(MINUTO);
    c1 = await entrar(h1, T1.usuaria);
    const imp3 = await importacaoTerminada(h1, c1, projeto1, { nome: 'Modelo da tarde', paginas: 1, estado: 'concluida' });
    await plantarResto(h1, imp3.id, [1]);
    await h1.clock.advance(HORA);
    expect(contagensExecucao(await logsDesde(h1, marca))).toHaveLength(2);
    expect(await h1.inspect.importacao(imp3.id)).toMatchObject({ estado: 'concluida', objetos: 1 });
  });
});

describe('CA-070 — reinício do processo', () => {
  let h2: Harness;
  let T2: TenantPronto;
  let c2: Cliente;
  let projeto2: string;
  let impX: any;

  beforeAll(async () => {
    // O processo reinicia: harness novo, relógio no mesmo dia civil de início (02/11/2026),
    // sem o último dia marcado em memória do processo anterior.
    h2 = await criarHarness();
    await prepararCotacao(h2);
    T2 = await tenantComUsuaria(h2, 'Tenant reiniciado');
    c2 = await entrar(h2, T2.usuaria);
    projeto2 = await projetoCriado(c2, 'Saúde 60+ reinício');
    impX = await importacaoTerminada(h2, c2, projeto2, { nome: 'Hábitos do reinício', paginas: 1, estado: 'concluida' });
  });
  afterAll(async () => {
    await h2?.close();
  });

  // @trace CA-070, CA-067, RF-016, RN-055, DEC-237
  it('CA-070 depois que o processo reinicia, executa no primeiro ciclo; rodar a mais não causa dano', async () => {
    // O processo anterior já tinha executado o job no dia civil 02/11; o novo executa mesmo
    // assim no primeiro ciclo, porque o último dia só vivia na memória do processo antigo.
    expect(contagensExecucao(await h1.inspect.logs()).length).toBeGreaterThanOrEqual(1);
    await h2.clock.advance(MINUTO);
    const execucoesAteAqui = contagensExecucao(await h2.inspect.logs()).length;
    expect(execucoesAteAqui).toBeGreaterThanOrEqual(1);

    // Uma vez só por dia, também no processo novo.
    await h2.clock.advance(HORA);
    expect(contagensExecucao(await h2.inspect.logs())).toHaveLength(execucoesAteAqui);

    // Resto plantado depois do primeiro ciclo: os ciclos do mesmo dia não o apagam.
    await plantarResto(h2, impX.id, [1]);
    await h2.clock.advance(HORA);
    expect(contagensExecucao(await h2.inspect.logs())).toHaveLength(execucoesAteAqui);
    expect(await h2.inspect.importacao(impX.id)).toMatchObject({ estado: 'concluida', objetos: 1 });

    // No primeiro ciclo do dia seguinte, o job limpa o resto.
    const marca = await marcaLogs(h2);
    await virarDiaCivil(h2);
    expect(await h2.inspect.importacao(impX.id)).toMatchObject({ chave_storage: null, objetos: 0 });
    const resumos = contagensExecucao(await logsDesde(h2, marca));
    expect(resumos).toHaveLength(1);
    expect(resumos[0].apagados).toBe(1);
    expect(resumos[0].falhas).toBe(0);

    // Rodar a mais não causa dano (CA-067): a execução seguinte termina sem erro, sem apagar
    // nada e sem auditar a importação de novo.
    const marca2 = await marcaLogs(h2);
    await virarDiaCivil(h2);
    const resumos2 = contagensExecucao(await logsDesde(h2, marca2));
    expect(resumos2).toHaveLength(1);
    expect(resumos2[0].apagados).toBe(0);
    expect(resumos2[0].falhas).toBe(0);
    expect(await auditoriaLimpeza(h2, T2.tenantId, impX.id)).toHaveLength(1);
  });
});
