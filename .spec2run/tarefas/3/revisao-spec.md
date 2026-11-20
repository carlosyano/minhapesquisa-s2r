# Revisão: spec

## Achados
- [MELHORIA] spec.md, CA-069: a SPEC diz que "o log da execução tem só as contagens, sem `.jpg`, `tenant/`, `importacao/`, conteúdo de arquivo ou mensagem de erro do sistema". Na REQ (CA-069), a proibição vale para a auditoria e para o log: "nem a auditoria nem o log têm...". Pela redação da SPEC, a auditoria parece ficar de fora. A RN-055 (1) já cobre a auditoria, então não há lacuna de regra, mas convém repetir o texto da REQ para que o teste confira os dois registros.
- [MELHORIA] spec.md, CA-064: a SPEC deixa de fora a tabela de exemplos da REQ. Faltam o exemplo 2 (`falhou` com `1.jpg` e `2.jpg`, porque a exclusão falhou depois da página 1) e o exemplo 3 (`concluida` em outro tenant "B", limpo pela própria pasta). Os dois são casos relevantes de resto parcial e de vários tenants. Convém citar a tabela ou remeter a ela, para que o TEST_DESIGNER cubra os três exemplos.
- [MELHORIA] spec.md, ERR-046: a REQ fixa o código `IMPORT_CLEANUP_FAILED`, o evento de log `import_cleanup_failed` e os campos permitidos (`tenant_id`, `importacao_id`, contagens e nome da classe do erro), além da auditoria `LIMPEZA_IMPORTACAO` com `falha`. A SPEC resume esses itens sem nomeá-los. Convém trazê-los para a SPEC, para que o teste e o código usem os mesmos nomes.
- [MELHORIA] design.md (fora do alvo, só para registro): o DESIGN ainda cita os IDs provisórios NRF-xxx, NCA-xxx, NRN-004 e NERR-xxx. A SPEC já os trocou pelos IDs da REQ (RF-016, RN-053 a RN-055, CA-064 a CA-070, ERR-046). O passo 1 do Plano também manda "incluir na REQ os critérios", o que a CHG-020 já fez. Convém alinhar o DESIGN antes do TEST_DESIGNER.

A SPEC está conforme o pedido e a REQ v2.10 (CHG-020, DEC-237). A RN-053 a RN-055, o RF-016, o CA-065 a CA-068, o CA-070 e o ERR-046 conferem com o texto da REQ. O pedido está todo coberto:
- só estados finais;
- nunca em andamento;
- reaplicável;
- sem nome de arquivo nem conteúdo no log;
- expurgo da RN-030 fora do escopo.

O requisito de segurança e privacidade está presente: isolamento por tenant, caminho montado só a partir do banco, lista fechada de estados e RN-028 no log e na auditoria. Nenhum requisito foi inventado. O RF-016 como USUARIO tem base no pedido e na decisão do responsável (DEC-237). O único requisito MUST tem CA, e os CA podem ser verificados, inclusive o CA-070, que usa o relógio injetado. Nível ELEVADO e Dados SINTETICO estão corretos (DEC-133). Não há pergunta aberta.

Observação: a CHG-020 ainda está como "proposta" no PLANO. A aprovação da tarefa depende do aceite da CHG pelo responsável, como o pedido já prevê.

VEREDITO: APROVADO
