# Pedido (issue #3)

## Job diário que apaga arquivos que sobraram de importações (F-21)

Implementar o achado F-21 do PLANO §12.3: o job diário que apaga os arquivos que sobrarem de
importações de formulário terminadas, previsto no PLANO §4.8 e na DEC-142 (RF-011).

Contexto: o worker já apaga os arquivos em `tenant/<tenant>/importacao/<importação>/` ao fim da
importação. Só uma exclusão que falhe deixa resto. O job diário apaga esse resto.

O que o job deve fazer:
- apagar os arquivos de importações que já terminaram (com sucesso ou falha);
- nunca apagar arquivos de uma importação que ainda está em andamento;
- ser reaplicável: rodar duas vezes seguidas não dá erro;
- não registrar em log o nome do arquivo nem o conteúdo (RN-028).

Fora do escopo: o expurgo da RN-030 e a lista de eliminações (continuam no IMP-004).

Se faltar critério de aceite na REQ para este job, aponte como item novo; ele entra por CHG
antes da aprovação.
