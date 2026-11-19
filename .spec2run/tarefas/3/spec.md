# SPEC: Job diário de limpeza de arquivos de importação (F-21)

Nível: ELEVADO
Dados: SINTETICO

## Contexto
A importação de formulário (RF-011, FL-004) grava os arquivos enviados em `tenant/<tenant>/importacao/<importação>/` e os apaga ao fim, quando a importação chega a `concluida` ou `falhou` (PLANO §4.8, DEC-142); quando essa exclusão falha, os arquivos sobram. O achado F-21 do PLANO §12.3 prevê um job diário de manutenção para apagar esse resto. Os arquivos de importação são formulários-modelo sem dado pessoal (DEC-133). A REQ não tem critério de aceite para esse job (CA-045 a CA-049 cobrem a importação, não a limpeza diária); os itens abaixo são propostos como item novo e entram por CHG antes da aprovação. A CHG anunciada também separa o F-21 do expurgo da RN-030: hoje o §12.3 registra o F-21 "adiado pelo responsável (05/11/2026) para o job diário de expurgo" (incremento IMP-004) e o §4.8 atribui a limpeza ao "job diário de expurgo"; a CHG deve atualizar a linha do F-21 (incremento e responsável) e o texto do §4.8, para a separação não parecer contradição com decisão registrada.

## Requisitos
- NRF-001 [FUNCIONAL][MUST][USUARIO] O job diário apaga os arquivos que sobraram na pasta `tenant/<tenant>/importacao/<importação>/` de toda importação em estado final (`concluida` ou `falhou`) que ainda tenha arquivo.
- NRF-002 [SEGURANCA][MUST][IA_INFERIDO] O job apaga somente dentro de `tenant/<tenant>/importacao/<importação>/`, com o caminho montado a partir do registro da ImportacaoFormulario (tenant e id do banco, não de nome lido do armazenamento); nunca apaga em pasta de aplicação, de exportação nem em pasta de outro tenant.
- NRF-003 [SEGURANCA][MUST][IA_INFERIDO] A decisão de apagar vem do estado da importação no banco: pasta sem registro de importação, ou cuja importação não está em estado final, nunca é apagada.
- NRF-004 [FUNCIONAL][MUST][USUARIO] O job nunca apaga arquivos de uma importação em estado não final (`enfileirada`, `aguardando_cota` ou `em_andamento`).
- NRF-005 [FUNCIONAL][MUST][USUARIO] O job é reaplicável: executado duas vezes seguidas, mesmo sem nenhum arquivo a apagar, termina sem erro.
- NRF-006 [PRIVACIDADE][MUST][USUARIO] O job não registra em log nem em auditoria o nome do arquivo nem o conteúdo; registra apenas identificadores e contagens (RN-028).
- NRF-007 [OPERACIONAL][MUST][USUARIO] O job é executado uma vez por dia, sem intervenção da usuária (o mecanismo de jobs de manutenção está no PLANO §4.7).
- NRF-008 [OPERACIONAL][MUST][IA_INFERIDO] Cada execução do job é auditada (PLANO §4.7), com tenant, id da importação e contagem de arquivos apagados, sem nome de arquivo.
- NRF-009 [OPERACIONAL][MUST][IA_INFERIDO] A falha ao apagar uma importação ou um tenant não interrompe a limpeza das demais, e a falha é registrada em log e auditoria apenas com identificadores e contagens (RN-028).

## Regras de negócio
- NRN-001 Arquivo de importação terminada (`concluida` ou `falhou`) é resto e deve ser apagado pelo job diário.
- NRN-002 Arquivo de importação em andamento (`enfileirada`, `aguardando_cota` ou `em_andamento`) nunca é apagado pelo job.
- NRN-003 O job registra em log e auditoria apenas identificadores e contagens, sem nome de arquivo nem conteúdo (RN-028).
- NRN-004 O job seleciona as importações pelo estado final no banco e varre a pasta derivada do id (`tenant/<tenant>/importacao/<importação>/`), sem depender do `chave_storage` para achar o resto; depois de apagar, o estado da importação não muda e só a auditoria é registrada.

## Critérios de aceite
- NCA-001 (NRF-001) Dado uma importação `concluida` com o arquivo ainda presente em `tenant/<tenant>/importacao/<importação>/` Quando o job diário executa Então o arquivo é apagado.
- NCA-002 (NRF-001) Dado uma importação `falhou` com o arquivo ainda presente Quando o job diário executa Então o arquivo é apagado.
- NCA-003 (NRF-004) Dado uma importação `em_andamento` com o arquivo presente Quando o job diário executa Então os arquivos continuam presentes e o estado da importação não muda.
- NCA-004 (NRF-004) Dado uma importação `aguardando_cota` com o arquivo presente Quando o job diário executa Então os arquivos continuam presentes e o estado da importação não muda.
- NCA-005 (NRF-004) Dado uma importação `enfileirada` com o arquivo presente Quando o job diário executa Então os arquivos continuam presentes e o estado da importação não muda.
- NCA-006 (NRF-005) Dado que o job diário já apagou todos os arquivos de importações terminadas Quando o job executa de novo em seguida Então a execução termina sem erro.
- NCA-007 (NRF-006) Dado um job diário que apaga arquivos de importações terminadas Quando a execução é registrada em log e auditoria Então o registro traz apenas identificadores e contagens, sem o nome de nenhum arquivo nem o conteúdo (RN-028).
- NCA-008 (NRF-007) Dado o mecanismo de jobs de manutenção em execução Quando um dia se passa Então o job é executado uma vez, sem intervenção da usuária.
- NCA-009 (NRF-002) Dado arquivos de aplicação, de exportação e de uma importação `concluida` no mesmo tenant Quando o job executa Então só os arquivos da importação são apagados; os de aplicação e de exportação permanecem.
- NCA-010 (NRF-002) Dado uma pasta de outro tenant (ou de aplicação ou de exportação) com arquivos Quando o job executa Então ela não é apagada.
- NCA-011 (NRF-003) Dado uma pasta em `tenant/<tenant>/importacao/<importação>/` sem registro de importação no banco, com arquivos Quando o job executa Então a pasta não é apagada.
- NCA-012 (NRF-008) Dado que o job apaga os arquivos de uma importação Quando a ação é auditada Então a auditoria registra o tenant, o id da importação e a contagem de arquivos apagados, sem nome de arquivo.
- NCA-013 (NRF-009) Dado uma falha ao apagar os arquivos de uma importação Quando o job executa Então as demais importações e tenants são limpos e a falha é registrada apenas com identificadores e contagens (RN-028).

## Casos de erro
- NERR-001 (NRF-001) Exclusão de um arquivo falha (arquivo ou pasta indisponível no armazenamento) -> o arquivo permanece e é tentado de novo na próxima execução diária; a limpeza das demais importações e tenants continua, e a falha é registrada em log e auditoria apenas com identificadores e contagens (RN-028).
- NERR-002 (NRF-005) Pasta de importação já totalmente apagada ou inexistente -> a execução segue sem erro (reaplicável).

## Fora do escopo
O expurgo da RN-030 (imagens, dados e exportações por retenção ou eliminação) e a lista de eliminações continuam no IMP-004. As linhas restantes de `tarefa_importacao` (o §4.8 manda apagar "os arquivos e as tarefas" ao fim; o worker já apaga as tarefas) e as pastas órfãs sem registro de importação não são tratadas por este job.

## Perguntas abertas
Nenhuma.
