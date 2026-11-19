# Revisão: spec

## Achados
- [MELHORIA] spec.md, NRN-004: a frase "o estado da importação não muda" não diz o que acontece com `chave_storage`. O REQ (ENT-031, campo `chave_storage`: "NULL depois de apagados") e o PLANO §4.8 mandam deixar o campo NULL depois que os arquivos são apagados. Se o worker não chegou a gravar NULL porque a exclusão falhou, o job precisa dizer se grava NULL depois de apagar o resto. Fixe isso na SPEC ou no DESIGN, de forma coerente com o §4.8 e com o padrão do job de exportação (§4.8, DEC-069).
- [MELHORIA] spec.md, NRF-008/NCA-012: "cada execução do job é auditada" com "tenant, id da importação e contagem" mistura dois níveis, a execução e cada importação. Diga se uma execução sem nada a apagar também gera registro de auditoria, por exemplo com contagem zero, ou se só a importação limpa é auditada. Isso evita ambiguidade no teste.
- [MELHORIA] spec.md, NCA-008: "Quando um dia se passa" é difícil de verificar de forma automática. Convém reformular como verificação do agendamento: o job está registrado no mecanismo de jobs de manutenção com periodicidade diária (PLANO §4.7).
- [MELHORIA] spec.md, NRF-003/NCA-011: vale citar FL-004 como base. Ali `concluida` e `falhou` são estados finais sem volta (uma nova tentativa é um novo envio), por isso apagar pelo estado final é seguro. Também vale um CA ou uma nota para a pasta cujo registro ainda não foi confirmado no banco, porque o arquivo é gravado na criação da importação. A NCA-011 cobre esse caso só de forma implícita, como "sem registro".

Todos os achados da rodada anterior foram corrigidos:
- limite de caminho e decisão pelo banco: NRF-002, NRF-003, NCA-009 a NCA-011;
- os três estados não finais: NCA-003 a NCA-005, com verificação que se pode testar;
- critério de seleção: NRN-004;
- isolamento de falhas: NRF-009, NCA-013 e NERR-001;
- auditoria: NRF-008 e NCA-012;
- Contexto da CHG sobre o F-21 e o §4.8;
- origem do NRF-007;
- Fora do escopo com `tarefa_importacao` e pastas órfãs.

Todo requisito MUST tem CA. Os estados conferem com ENT-031 e FL-004. Nível ELEVADO e Dados SINTETICO estão corretos, porque o arquivo é formulário-modelo sem dado pessoal (DEC-133).

VEREDITO: APROVADO
