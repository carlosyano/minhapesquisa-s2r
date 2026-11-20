// Agendador do job diário de manutenção (ADR-004 do DESIGN, CA-070): roda uma vez por dia civil de
// America/Sao_Paulo, sem dependência nova. O último dia fica só em memória e é marcado ao iniciar a
// execução, para que uma falha geral (banco fora) não repita o job em todo ciclo; o que falhou é
// tentado no dia seguinte (ERR-046). Reiniciar o processo executa no primeiro ciclo de novo.

import type { Nucleo } from '../nucleo.js';

const FUSO = 'America/Sao_Paulo';

export class AgendadorDiario {
  private ultimoDia: string | undefined;
  private rodando = false;

  constructor(
    private readonly n: Nucleo,
    private readonly tarefa: () => Promise<unknown>,
  ) {}

  /** Executa a tarefa no primeiro ciclo de cada dia civil; nos demais ciclos, não faz nada. */
  async tick(): Promise<void> {
    const dia = this.diaCivil(this.n.agora());
    if (this.rodando || dia === this.ultimoDia) return;
    this.rodando = true;
    this.ultimoDia = dia;
    try {
      await this.tarefa();
    } finally {
      this.rodando = false;
    }
  }

  private diaCivil(d: Date): string {
    const partes = new Intl.DateTimeFormat('en-US', {
      timeZone: FUSO,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).formatToParts(d);
    const valor = (tipo: 'year' | 'month' | 'day') => partes.find((p) => p.type === tipo)?.value ?? '';
    return `${valor('year')}-${valor('month')}-${valor('day')}`;
  }
}
