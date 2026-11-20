// Job diário de limpeza dos arquivos que sobraram de importações terminadas (RF-016, RN-053 a
// RN-055, CA-064 a CA-069, ERR-046; CHG-020, DEC-237, F-21 do PLANO §12.3, IMP-011).
//
// A importação escolhida vem do banco pelo estado final; a pasta e as chaves são montadas só com o
// tenant e o identificador da importação, sem listar o armazenamento nem usar o chave_storage
// (RN-054). Cada importação é limpa isoladamente: a falha de uma não interrompe as demais (CA-068).
// Nada do conteúdo ou do caminho entra no log nem na auditoria (RN-028).

import { linhas, sql } from '../infra/banco.js';
import { chavePaginaImportacao, pastaImportacao } from '../leitura/importacao.js';
import type { Nucleo } from '../nucleo.js';

export interface ResumoLimpeza {
  verificadas: number;
  apagados: number;
  falhas: number;
}

interface Importacao {
  id: string;
  tenant_id: string;
  total_paginas: number;
}

const sistema = (tenantId: string) => ({ tenantId, usuarioId: null, ip: null });

export class LimpezaImportacao {
  constructor(private readonly n: Nucleo) {}

  /** Apaga o resto de todas as importações em estado final e devolve as contagens do dia. */
  async executar(): Promise<ResumoLimpeza> {
    // Lista fechada de estados finais (RN-053 (3)): um estado novo ou inesperado nunca é apagado.
    const importacoes = await this.n.banco.manutencao((tx) =>
      linhas<Importacao>(
        tx,
        sql`SELECT id, tenant_id, total_paginas FROM importacao_formulario
             WHERE estado IN ('concluida', 'falhou') ORDER BY tenant_id, id`,
      ),
    );

    let apagados = 0;
    let falhas = 0;
    for (const i of importacoes) {
      try {
        const r = await this.limpar(i);
        apagados += r.apagados;
        if (r.falha) falhas += 1;
      } catch (e) {
        // Uma importação nunca interrompe as demais (CA-068, ERR-046). Sem contagem medida,
        // o log não afirma apagados nem restantes.
        falhas += 1;
        this.n.log(
          `import_cleanup_failed tenant_id=${i.tenant_id} importacao_id=${i.id} erro=${e instanceof Error ? e.name : 'erro'}`,
        );
      }
    }
    this.n.log(`limpeza_importacao_execucao verificadas=${importacoes.length} apagados=${apagados} falhas=${falhas}`);
    return { verificadas: importacoes.length, apagados, falhas };
  }

  private async limpar(i: Importacao): Promise<{ apagados: number; falha: boolean }> {
    const pasta = pastaImportacao(i.tenant_id, i.id);
    let antes: number;
    try {
      antes = await this.n.config.armazenamento.contar(pasta);
    } catch (e) {
      return this.registrarFalha(i, 0, 0, e);
    }
    // Sem resto não há auditoria nem escrita (RN-055 (2), CA-067).
    if (antes === 0) return { apagados: 0, falha: false };

    const chaves = Array.from({ length: i.total_paginas }, (_, k) => chavePaginaImportacao(i.tenant_id, i.id, k + 1));
    const resultados = await Promise.allSettled(chaves.map((chave) => this.n.config.armazenamento.apagar(chave)));
    const rejeitada = resultados.find((r): r is PromiseRejectedResult => r.status === 'rejected');
    let restantes: number;
    try {
      restantes = await this.n.config.armazenamento.contar(pasta);
    } catch (e) {
      return this.registrarFalha(i, antes, antes, rejeitada?.reason ?? e);
    }
    const apagados = Math.max(0, antes - restantes);
    if (rejeitada || restantes > 0) {
      return this.registrarFalha(i, apagados, restantes, rejeitada?.reason ?? new Error('resto não apagado'));
    }

    try {
      await this.n.banco.noTenant(i.tenant_id, async (tx) => {
        await this.n.auditar(tx, sistema(i.tenant_id), 'LIMPEZA_IMPORTACAO', 'ImportacaoFormulario', i.id, { apagados, restantes: 0 });
        await tx.execute(sql`
          UPDATE importacao_formulario SET chave_storage = NULL
           WHERE id = ${i.id} AND chave_storage IS NOT NULL`);
      });
    } catch (e) {
      return this.registrarFalha(i, apagados, 0, e);
    }
    return { apagados, falha: false };
  }

  /** ERR-046: log e auditoria só com identificadores, contagens e o nome da classe do erro. */
  private async registrarFalha(i: Importacao, apagados: number, restantes: number, erro: unknown): Promise<{ apagados: number; falha: boolean }> {
    const nome = erro instanceof Error ? erro.name : 'erro';
    this.n.log(
      `import_cleanup_failed tenant_id=${i.tenant_id} importacao_id=${i.id} apagados=${apagados} restantes=${restantes} erro=${nome}`,
    );
    try {
      await this.n.banco.noTenant(i.tenant_id, (tx) =>
        this.n.auditar(tx, sistema(i.tenant_id), 'LIMPEZA_IMPORTACAO', 'ImportacaoFormulario', i.id, {
          apagados,
          restantes,
          falha: true,
          erro: nome,
        }),
      );
    } catch (e) {
      // Banco fora: a falha principal já foi registrada uma única vez; a da auditoria sai com
      // outro evento, só com identificadores e o nome da classe (ERR-046, RN-028).
      this.n.log(
        `import_cleanup_audit_failed tenant_id=${i.tenant_id} importacao_id=${i.id} erro=${e instanceof Error ? e.name : 'erro'}`,
      );
    }
    return { apagados, falha: true };
  }
}
