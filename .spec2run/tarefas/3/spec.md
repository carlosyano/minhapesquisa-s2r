# SPEC: Job diário de limpeza de arquivos de importação (F-21)

Nível: ELEVADO
Dados: SINTETICO

## Contexto
A importação de formulário (RF-011, FL-004) grava os arquivos enviados em `tenant/<tenant>/importacao/<importação>/` e os apaga ao fim, quando a importação chega a `concluida` ou `falhou` (PLANO §4.8, DEC-142). Quando essa exclusão falha, os arquivos sobram. O achado F-21 do PLANO §12.3 prevê um job diário de manutenção para apagar esse resto. Os arquivos de importação são formulários-modelo sem dado pessoal (DEC-133). A REQ não tem critério de aceite para esse job (os CA-045 a CA-049 cobrem a importação, não a limpeza diária); os requisitos e critérios abaixo são propostos como item novo e entram por CHG antes da aprovação.

## Requisitos
- REQ-001 [FUNCIONAL][MUST][USUARIO] O job diário apaga os arquivos da pasta `tenant/<tenant>/importacao/<importação>/` de toda importação em estado final (`concluida` ou `falhou`) que ainda tenha arquivo.
- REQ-002 [FUNCIONAL][MUST][USUARIO] O job nunca apaga arquivos de uma importação em estado não final (`enfileirada`, `aguardando_cota` ou `em_andamento`).
- REQ-003 [FUNCIONAL][MUST][USUARIO] O job é reaplicável: executado duas vezes seguidas, mesmo sem nenhum arquivo a apagar, não gera erro.
- REQ-004 [PRIVACIDADE][MUST][USUARIO] O job não registra em log nem em auditoria o nome do arquivo nem o conteúdo; registra apenas identificadores e contagens (RN-028).
- REQ-005 [OPERACIONAL][MUST][USUARIO] O job é executado uma vez por dia pelo agendador de manutenção (`mp_manutencao`), sem intervenção da usuária.

## Regras de negócio
- RN-001 Arquivo de importação terminada (`concluida` ou `falhou`) é resto e deve ser apagado pelo job diário.
- RN-002 Arquivo de importação em andamento (`enfileirada`, `aguardando_cota` ou `em_andamento`) nunca é apagado pelo job.
- RN-003 O job registra em log apenas identificadores e contagens, sem nome de arquivo nem conteúdo (RN-028).

## Critérios de aceite
- CA-001 (REQ-001) Dado uma importação `concluida` com o arquivo ainda presente em `tenant/<tenant>/importacao/<importação>/` Quando o job diário executa Então o arquivo é apagado.
- CA-002 (REQ-001) Dado uma importação `falhou` com o arquivo ainda presente Quando o job diário executa Então o arquivo é apagado.
- CA-003 (REQ-002) Dado uma importação `em_andamento` com o arquivo presente Quando o job diário executa Então o arquivo é mantido e o processamento continua.
- CA-004 (REQ-003) Dado que o job diário já apagou todos os arquivos de importações terminadas Quando o job executa de novo em seguida Então a execução termina sem erro.
- CA-005 (REQ-004) Dado um job diário que apaga arquivos de importações terminadas Quando a execução é registrada em log Então o registro traz apenas identificadores e contagens, sem o nome de nenhum arquivo nem o conteúdo (RN-028).
- CA-006 (REQ-005) Dado o agendador de manutenção em execução Quando um dia se passa Então o job é executado uma vez, sem intervenção da usuária.

## Casos de erro
- ERR-001 (REQ-001) Exclusão de um arquivo falha (arquivo ou pasta indisponível no armazenamento) -> o arquivo permanece e é tentado de novo na próxima execução diária, sem erro e sem o nome do arquivo em log (RN-028).
- ERR-002 (REQ-003) Pasta de importação já totalmente apagada ou inexistente -> a execução segue sem erro (reaplicável).

## Fora do escopo
O expurgo da RN-030 (imagens, dados e exportações por retenção ou eliminação) e a lista de eliminações continuam no IMP-004.

## Perguntas abertas
Nenhuma.
