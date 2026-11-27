"""Spec2Run 1.4: lista e classifica os riscos por REGRA DE CÓDIGO, nunca por IA.

Por que existe: na 1.4 o PO não aprova código (não tem como avaliá-lo); ele aceita riscos. Para
esse aceite valer alguma coisa, quem lista e classifica os riscos não pode ser quem construiu.
Este módulo lê evidências objetivas (registro, varreduras, git) e devolve a lista. A IA que
escreve o relatório em linguagem simples recebe a lista pronta e só pode explicá-la: a máquina
recusa o relatório que omita risco, mude nível ou invente risco (ler_relatorio).

Níveis (decisão do Carlos, DL-54):
  A  bloqueante: ninguém aceita.
  B  o PO aceita com declaração escrita de quem foi consultado.
  C  o PO aceita sozinho.
Regra de ouro: um risco gerado por regra nunca é removido nem rebaixado; a IA só pode subir.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone

from . import core
from .core import ErroFL, ler, sha256

# ----------------------------------------------------------------------------- catálogo
# Texto padrão de cada regra: escrito por humano, em português simples. É ele (mais os números
# da evidência) que o PO aceita e que vai para o registro, não a prosa da IA.
CATALOGO = {
    # --- A: bloqueantes
    "A_TESTE_ALTERADO": ("A", "Teste aprovado foi alterado",
        "Os testes que você aprovou depois do RED não são mais os mesmos. Sem testes iguais aos aprovados, o 'verde' não prova nada.", []),
    "A_AREA_PROTEGIDA": ("A", "Área protegida foi alterada",
        "O código mexeu em arquivos que só uma pessoa pode alterar (regras do processo, configuração de segurança ou de teste).", []),
    "A_VERIFICACAO_DESLIGADA": ("A", "Verificação obrigatória desligada ou ausente",
        "Uma verificação que nunca pode faltar (testes, varredura de segurança, segredos, dependências) não rodou ou foi desligada.", []),
    "A_HASH": ("A", "Integridade do registro não confere",
        "O registro da tarefa ou a SPEC e o DESIGN aprovados foram alterados fora da máquina.", []),
    "A_REVISOR_MESMO_FORNECEDOR": ("A", "Revisor do mesmo fornecedor de quem escreveu o código",
        "A revisão independente foi feita pelo mesmo fornecedor do construtor, sem exceção humana registrada. Não é revisão independente.", []),
    "A_SEGREDO": ("A", "Segredo exposto no código",
        "A busca por senhas e chaves encontrou algo. Segredo exposto precisa ser removido e revogado antes de qualquer entrega.", []),
    "A_DADO_REAL": ("A", "Possível dado pessoal real em código ou teste",
        "A varredura por padrões achou o que parece dado pessoal real (por exemplo, CPF válido ou e-mail verdadeiro) no código ou nos testes. Agentes e testes só podem usar dado sintético.", []),
    "A_REQ_SEM_TESTE": ("A", "Requisito obrigatório sem teste",
        "Há critério de aceite obrigatório (MUST) que nenhum teste cita.", []),
    "A_DIFF_ACIMA_LIMITE": ("A", "Diff maior do que o revisor consegue ler",
        "Parte do código não foi lida pelo revisor independente, mesmo com a revisão em partes (um arquivo é maior do que o limite de leitura, ou a mudança precisaria de mais partes do que o permitido). Ninguém aceita esse risco; a tarefa precisa ser fatiada em partes menores.", []),
    "A_TETO_GASTO": ("A", "Teto de gasto de IA atingido",
        "O limite de gasto com IA foi atingido; a tarefa fica parada até quem a conduz definir outro limite ou esperar o próximo ciclo.", []),
    "A_VULN_CRITICA": ("A", "Vulnerabilidade de severidade crítica",
        "A varredura encontrou vulnerabilidade crítica. Ela precisa ser corrigida; ninguém pode aceitá-la.", []),
    # --- B: aceite com declaração de consulta
    "B_VULN_ALTA": ("B", "Vulnerabilidade de severidade alta",
        "A varredura encontrou vulnerabilidade de severidade alta. Consulte a área de segurança da informação antes de aceitar.", ["SegInfo"]),
    "B_SEM_SEVERIDADE": ("B", "Achado de segurança sem severidade legível",
        "Uma varredura rodou, mas a máquina não conseguiu ler a gravidade do que ela achou. Na dúvida, trata-se como risco médio-alto.", ["SegInfo"]),
    "B_CONTRATO": ("B", "Contrato da API alterado",
        "O contrato da API (o que outros sistemas esperam) foi alterado. A verificação de compatibilidade passou, mas quem usa a API precisa saber.", ["Dono da API", "SegInfo"]),
    "B_DADO_PESSOAL": ("B", "Tratamento de dado pessoal ou sensível",
        "Esta tarefa trata dado pessoal ou sensível (por exemplo, saúde). Consulte o responsável por proteção de dados antes de aceitar.", ["DPO", "Jurídico"]),
    "B_DEPENDENCIA": ("B", "Dependência nova ou trocada",
        "Entrou ou mudou uma biblioteca de terceiros. Cada biblioteca é código que ninguém desta empresa escreveu.", ["SegInfo"]),
    "B_EXCECAO_DIVERSIDADE": ("B", "Exceção à separação de fornecedores",
        "Por decisão humana registrada, dois papéis que deveriam ser de fornecedores diferentes são do mesmo fornecedor.", ["SegInfo"]),
    "B_MUTACAO_ABAIXO": ("B", "Teste de mutação abaixo da meta",
        "Depois de várias tentativas, os testes ainda não pegam todas as falhas simuladas no código. O código passa, mas é menos vigiado do que o combinado.", []),
    "B_PLANO_PESSOAL": ("B", "Plano pessoal de IA usado em automação",
        "Um ou mais agentes usam plano pessoal de IA, cujos termos podem proibir automação (risco de bloqueio da chave). Quem adotou o processo assumiu esse risco por escrito; confirme com o Jurídico antes de usar em produção.", ["Jurídico"]),
    "B_REVISAO_ALTO": ("B", "Risco alto apontado pela revisão independente",
        "A revisão independente (de outra IA) apontou risco que ela mesma classificou como alto.", []),
    "B_VULN_AGREGADA": ("B", "Muitas vulnerabilidades baixas ou médias",
        "Cada vulnerabilidade baixa ou média seria um aceite simples, mas o conjunto passou do limite e pede consulta.", ["SegInfo"]),
    # --- C: o PO aceita sozinho
    "C_VULN_BAIXA_MEDIA": ("C", "Vulnerabilidades de severidade baixa ou média",
        "A varredura encontrou vulnerabilidades de severidade baixa ou média.", []),
    "C_REVISAO_MELHORIAS": ("C", "Melhorias sugeridas pela revisão independente",
        "A revisão independente sugeriu ajustes que não impedem a entrega.", []),
    "C_REVISAO_DESEMPENHO": ("C", "Risco de desempenho apontado pela revisão",
        "A revisão independente apontou possível problema de desempenho.", []),
    "C_REVISAO_DIVIDA": ("C", "Dívida técnica apontada pela revisão",
        "A revisão independente apontou dívida técnica (algo que vai custar mais manutenção depois).", []),
    "C_ALTERACAO_GRANDE": ("C", "Alteração grande",
        "A alteração é grande, o que torna mais fácil algo passar despercebido.", []),
    "C_CRITERIO_NAO_ATENDIDO": ("C", "Critério opcional não atendido",
        "Um critério de aceite não obrigatório (SHOULD ou COULD) foi marcado como 'não atende' pelo PO.", []),
    "C_MITIGACAO_NAO_EFICAZ": ("C", "Mitigação não eficaz",
        "A IA tentou mitigar o risco e a regra de código continuou encontrando-o.", []),
    # --- C: o que não foi verificado (calculado por código, aparece sempre que valer)
    "NV_PASSOS_NAO_RODADOS": ("C", "Verificações que não rodaram",
        "Estas verificações não existem ou não rodaram nesta tarefa, então ninguém conferiu essa parte.", []),
    "NV_DIFF_NAO_LIDO": ("C", "Código que a revisão independente não leu",
        "Parte da alteração era grande demais e a revisão independente não a leu. Nenhuma IA ou pessoa viu esses arquivos.", []),
    "NV_MUTACAO_NAO_RODADA": ("C", "Teste de mutação não rodou",
        "O teste de mutação (que mede se os testes pegam falhas no código) não rodou nesta tarefa.", []),
    "NV_GASTO_NAO_MEDIDO": ("C", "Gasto com IA não medido",
        "O custo desta tarefa não foi medido em todos os papéis. Quem corta o gasto de verdade é o painel de cada fornecedor.", []),
    "NV_DADO_REAL_PADROES": ("C", "Dado real: só varredura por padrões",
        "A checagem de dado pessoal real procura padrões (CPF válido, e-mail verdadeiro). Não achar nada não prova que não há dado real.", []),
}

PASSOS_NAO_RODADOS = ("DEPLOY", "SMOKE", "ROLLBACK", "LICENCAS")
ORDEM_NIVEL = {"A": 0, "B": 1, "C": 2}


# ----------------------------------------------------------------------------- medições
def _json_da_saida(texto: str):
    """O JSON dentro da saída de uma ferramenta (ela pode imprimir texto antes e depois)."""
    texto = texto or ""
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        pass
    dec = json.JSONDecoder()
    for m in re.finditer(r"[{\[]", texto):
        try:
            return dec.raw_decode(texto[m.start():])[0]
        except json.JSONDecodeError:
            continue
    return None


def parse_medicao(formato: str, texto: str) -> dict | None:
    """Contagem por severidade {critica, alta, media, baixa}, ou None se a saída não é legível."""
    j = _json_da_saida(texto)
    if not isinstance(j, dict):
        return None
    if formato == "npm-audit-json":
        v = (j.get("metadata") or {}).get("vulnerabilities")
        if not isinstance(v, dict):
            return None
        return {"critica": int(v.get("critical", 0)), "alta": int(v.get("high", 0)),
                "media": int(v.get("moderate", 0)), "baixa": int(v.get("low", 0)) + int(v.get("info", 0))}
    if formato == "semgrep-json":
        res = j.get("results")
        if not isinstance(res, list):
            return None
        c = {"critica": 0, "alta": 0, "media": 0, "baixa": 0}
        for r in res:
            sev = str(((r or {}).get("extra") or {}).get("severity", "")).upper()
            c[{"CRITICAL": "critica", "ERROR": "alta", "HIGH": "alta", "WARNING": "media", "MEDIUM": "media"}.get(sev, "baixa")] += 1
        return c
    return None


# ----------------------------------------------------------------------------- contexto (fatos)
def _git(repo: str, *a: str) -> str:
    p = subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True, errors="replace")
    return p.stdout if p.returncode == 0 else ""


def _mostrar(repo: str, rev: str, caminho: str) -> str | None:
    p = subprocess.run(["git", "show", f"{rev}:{caminho}"], cwd=repo, capture_output=True, text=True, errors="replace")
    return p.stdout if p.returncode == 0 else None


def _cpf_valido(s: str) -> bool:
    d = [int(x) for x in re.sub(r"\D", "", s)]
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for n in (9, 10):
        soma = sum(d[i] * (n + 1 - i) for i in range(n))
        if (soma * 10 % 11) % 10 != d[n]:
            return False
    return True


EMAILS_RESERVADOS = re.compile(r"@(?:[\w-]+\.)*(?:example\.(?:com|org|net)|invalid|test|localhost|exemplo\.[a-z]+)\b", re.I)


def varrer_dados_reais(diff_u0: str, permitir: list[str] | None = None) -> list[str]:
    """Procura padrões de dado pessoal real nas linhas ACRESCENTADAS. Devolve achados MASCARADOS
    (nunca o dado). Varredura por padrões: ausência de achado não prova ausência de dado real."""
    achados, arquivo = [], "?"
    permitir = [re.compile(x) for x in (permitir or [])]
    for linha in diff_u0.splitlines():
        if linha.startswith("+++ "):
            arquivo = linha[6:] if linha.startswith("+++ b/") else linha[4:]
        elif linha.startswith("+") and not linha.startswith("+++"):
            for m in re.finditer(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", linha):
                if _cpf_valido(m.group(0)) and not any(r.search(m.group(0)) for r in permitir):
                    achados.append(f"{arquivo}: CPF com dígitos verificadores válidos ({m.group(0)[:3]}***)")
            for m in re.finditer(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", linha):
                if not EMAILS_RESERVADOS.search(m.group(0)) and not any(r.search(m.group(0)) for r in permitir):
                    achados.append(f"{arquivo}: e-mail de domínio real ({m.group(0)[:2]}***@{m.group(0).split('@')[1]})")
    return achados[:20]


def _tags_revisao(md: str) -> dict:
    t = {"alto": [], "melhorias": [], "desempenho": [], "divida": []}
    for linha in md.splitlines():
        m = re.match(r"^- \[(ALTO|MELHORIA|DESEMPENHO|DIVIDA)\]\s*(.*)$", linha)
        if m:
            t[{"ALTO": "alto", "MELHORIA": "melhorias", "DESEMPENHO": "desempenho", "DIVIDA": "divida"}[m.group(1)]].append(m.group(2)[:200])
    return t


def coletar_contexto(repo: str, tarefa_dir: str, cfg: dict, st: "core.Estado", base: str = "origin/main") -> dict:
    """Os fatos que as regras leem. Tudo vem do registro, do git ou dos arquivos: nada vem da IA."""
    rc = cfg.get("riscos") or {}
    evs = core.Registro(tarefa_dir).eventos()
    ctx: dict = {}
    # integridade
    try:
        core.Registro(tarefa_dir).verificar()
        ctx["integridade_ok"] = not (st.bloqueio and "depois da sua aprovação" in st.bloqueio) and not (
            st.bloqueio and "cadeia do registro" in st.bloqueio)
    except ErroFL:
        ctx["integridade_ok"] = False
    # testes
    esperado = st.hash_testes_aprovado if cfg.get("aprovar_testes") else st.testes_hash
    ctx["teste_alterado"] = bool(esperado) and core.hash_testes(repo, cfg) != esperado
    # git
    rel = os.path.relpath(tarefa_dir, repo).replace(os.sep, "/")
    mudou = [x for x in _git(repo, "diff", "--name-only", "--no-renames", f"{base}...HEAD").split() if not x.startswith(f"{rel}/")]
    prot = list(core.ZONA_PROIBIDA) + list(cfg.get("protegidos", []))
    ctx["protegidos_alterados"] = [c for c in mudou if core.casa(c, prot) and not c.startswith(".spec2run/tarefas/")]
    num = _git(repo, "diff", "--numstat", "--no-renames", f"{base}...HEAD", "--", ".",
               *[f":(exclude){x}" for x in core.DIFF_EXCLUIR])
    linhas = 0
    for l in num.splitlines():
        a = l.split("\t")
        if len(a) >= 3 and a[0].isdigit() and a[1].isdigit():
            linhas += int(a[0]) + int(a[1])
    ctx["tamanho"] = {"linhas": linhas, "arquivos": len([x for x in mudou if not core.casa(x, core.DIFF_EXCLUIR)])}
    ctx["contrato_alterado"] = [c for c in mudou if core.casa(c, rc.get("contrato_globs", ["contracts/**", "**/openapi*.yaml", "**/openapi*.yml", "**/openapi*.json"]))]
    deps = []
    for c in mudou:
        if core.casa(c, ["package.json", "**/package.json"]) and "node_modules/" not in c:
            try:
                antes = json.loads(_mostrar(repo, f"{base}", c) or "{}")
                depois = json.loads(_mostrar(repo, "HEAD", c) or "{}")
            except json.JSONDecodeError:
                deps.append(f"{c}: package.json ilegível")
                continue
            for k in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
                a, d = antes.get(k) or {}, depois.get(k) or {}
                deps += [f"{n} ({c})" for n in sorted(d) if a.get(n) != d[n]]
    ctx["dependencias_alteradas"] = deps
    diff_u0 = _git(repo, "diff", "-U0", "--no-renames", "--no-color", f"{base}...HEAD", "--", ".",
                   *[f":(exclude){x}" for x in core.DIFF_EXCLUIR])
    ctx["dados_reais"] = varrer_dados_reais(diff_u0, rc.get("dados_reais_permitir"))
    # SPEC e testes
    try:
        s = core.spec_da_tarefa(repo, tarefa_dir, cfg)
        arqs = core.arquivos_de_teste(repo, tarefa_dir, cfg)
        texto = "\n".join(ler(os.path.join(repo, a)) for a in arqs)
        ctx["cas_sem_teste"] = [c for c in s.cas_must() if not re.search(rf"\b{re.escape(c)}\b", texto)]
        ctx["dados"] = s.dados
    except ErroFL as e:
        ctx["cas_sem_teste"], ctx["dados"] = [], st.dados
        ctx["erro_spec"] = str(e)[:200]
    # passos de GREEN
    ctx["passos_ausentes"] = [n for n in core.PASSOS_MINIMOS_GREEN
                              if n not in st.passos_green
                              or (not st.passos_green[n] and (cfg["comandos"].get(n) or {}).get("modo") != "medicao")]
    ctx["segredos_ok"] = st.passos_green.get("SEGREDOS", False)
    ctx["medicoes"] = st.medicoes
    ctx["mutacao_abaixo"] = st.mutacao_abaixo
    # fornecedores
    ctx["forn_revisor"] = next((e["dados"].get("fornecedor") for e in reversed(evs) if e["evento"] == "ENTREGA_ACEITA"
                                and e["dados"].get("papel") == "REVIEWER" and e["dados"].get("alvo") == "codigo"), None)
    ctx["forn_builder"] = next((e["dados"].get("fornecedor") for e in reversed(evs) if e["evento"] == "ENTREGA_ACEITA"
                                and e["dados"].get("papel") == "BUILDER"), None)
    ctx["excecoes"] = [x["papeis"] for x in cfg.get("diversidade_excecoes") or []]
    ctx["excecao_revisor"] = bool(core.excecao_diversidade(cfg, "REVIEWER", "BUILDER"))
    ctx["previa_modo"] = st.previa_modo
    ctx["teto"] = st.teto
    # revisão independente
    c = os.path.join(tarefa_dir, "revisao-codigo.md")
    ctx["revisao"] = _tags_revisao(ler(c)) if os.path.exists(c) else _tags_revisao("")
    # aceite do PO
    ctx["ca_nao_must_nao_atendidos"] = sorted(c["id"] for c in st.cas if not c.get("must")
                                              and (st.aceites.get(c["id"]) or {}).get("resultado") == "nao-atende")
    # o que não foi verificado
    cm = cfg.get("comandos", {})
    ctx["passos_nao_rodados"] = [n for n in PASSOS_NAO_RODADOS if not (cm.get(n) or {}).get("cmd")
                                 or (st.passos_rodados and n not in st.passos_rodados)]
    ctx["diff_nao_lido"] = list(st.diff_nao_lido)
    ctx["planos_pessoais"] = sorted(p for p, r in cfg.get("papeis", {}).items() if r.get("plano") == "plano_pessoal")
    ctx["mutacao_nao_rodada"] = not ("MUTACAO" in st.passos_rodados)
    papeis_usados = sorted({e["dados"]["papel"] for e in evs if e["evento"] == "ENTREGA_ACEITA"})
    com_custo = {e["dados"]["papel"] for e in evs if e["evento"] == "CUSTO" and e["dados"].get("usd") is not None}
    ctx["gasto_nao_medido"] = [p for p in papeis_usados if p not in com_custo]
    ctx["mitigacao_nao_eficaz"] = list(st.seguir_chaves)
    return ctx


# ----------------------------------------------------------------------------- classificação
def _item(regra: str, evidencia: str, quantidade: int = 1, chave: str | None = None, consultar=None) -> dict:
    nivel, titulo, texto, cons = CATALOGO[regra]
    return {"chave": chave or regra, "regra": regra, "nivel": nivel, "titulo": titulo, "texto": texto,
            "evidencia": evidencia, "consultar": list(consultar if consultar is not None else cons), "quantidade": quantidade}


def classificar(ctx: dict, cfg: dict) -> list[dict]:
    """A lista de riscos. Função pura: mesma entrada, mesma lista. Nenhuma IA participa."""
    rc = cfg.get("riscos") or {}
    out: list[dict] = []

    def add(*a, **k):
        out.append(_item(*a, **k))

    # ---- A
    if ctx.get("teste_alterado"):
        add("A_TESTE_ALTERADO", "o hash dos arquivos de teste difere do aprovado")
    if ctx.get("protegidos_alterados"):
        add("A_AREA_PROTEGIDA", "arquivos: " + ", ".join(ctx["protegidos_alterados"][:10]))
    if ctx.get("passos_ausentes"):
        add("A_VERIFICACAO_DESLIGADA", "faltam ou falharam: " + ", ".join(ctx["passos_ausentes"]))
    if ctx.get("integridade_ok") is False:
        add("A_HASH", "a cadeia do registro ou o hash da SPEC e do DESIGN aprovados não confere")
    fr, fb = ctx.get("forn_revisor"), ctx.get("forn_builder")
    if fr and fb and fr == fb and not ctx.get("excecao_revisor"):
        add("A_REVISOR_MESMO_FORNECEDOR", f"revisor e construtor são do fornecedor '{fr}'")
    if ctx.get("segredos_ok") is False:
        add("A_SEGREDO", "a busca por segredos não passou")
    if ctx.get("dados_reais"):
        add("A_DADO_REAL", "; ".join(ctx["dados_reais"][:5]) + " (varredura por padrões, dado mascarado)")
    if ctx.get("cas_sem_teste"):
        add("A_REQ_SEM_TESTE", "critérios sem teste: " + ", ".join(ctx["cas_sem_teste"]))
    if ctx.get("diff_nao_lido"):
        add("A_DIFF_ACIMA_LIMITE", "arquivos não lidos: " + ", ".join(ctx["diff_nao_lido"][:10]), len(ctx["diff_nao_lido"]))
    if ctx.get("teto"):
        add("A_TETO_GASTO", f"papel {ctx['teto'].get('papel')}: {ctx['teto'].get('motivo', '')[:200]}")
    # ---- medições (severidade)
    soma = {"critica": 0, "alta": 0, "media": 0, "baixa": 0}
    ilegiveis = []
    for nome, m in (ctx.get("medicoes") or {}).items():
        if not m.get("legivel") or m.get("contagem") is None:
            ilegiveis.append(nome)
            continue
        for k in soma:
            soma[k] += int(m["contagem"].get(k, 0))
    if soma["critica"]:
        add("A_VULN_CRITICA", f"{soma['critica']} achado(s) de severidade crítica")
    if soma["alta"]:
        add("B_VULN_ALTA", f"{soma['alta']} achado(s) de severidade alta")
    if ilegiveis:
        add("B_SEM_SEVERIDADE", "sem severidade legível em: " + ", ".join(ilegiveis))
    leves = soma["media"] + soma["baixa"]
    if leves:
        limite = int(rc.get("agregar_c_acima_de", 5))
        if leves > limite:
            add("B_VULN_AGREGADA", f"{leves} achados de severidade baixa ou média (limite para aceite simples: {limite})", leves)
        else:
            add("C_VULN_BAIXA_MEDIA", f"{leves} achado(s): {soma['media']} média(s), {soma['baixa']} baixa(s)", leves)
    # ---- B
    if ctx.get("contrato_alterado"):
        add("B_CONTRATO", "arquivos: " + ", ".join(ctx["contrato_alterado"][:5]))
    if ctx.get("dados") in ("PESSOAL", "SENSIVEL"):
        add("B_DADO_PESSOAL", f"a SPEC declara Dados: {ctx['dados']}")
    if ctx.get("dependencias_alteradas"):
        add("B_DEPENDENCIA", "novas ou trocadas: " + ", ".join(ctx["dependencias_alteradas"][:10]), len(ctx["dependencias_alteradas"]))
    for par in ctx.get("excecoes") or []:
        add("B_EXCECAO_DIVERSIDADE", f"{' e '.join(par)} no mesmo fornecedor, por exceção registrada no config.json",
            chave="B_EXCECAO_DIVERSIDADE:" + "+".join(sorted(par)))
    if ctx.get("mutacao_abaixo"):
        add("B_MUTACAO_ABAIXO", f"abaixo da meta depois de {ctx['mutacao_abaixo'].get('tentativas')} tentativas")
    if ctx.get("planos_pessoais"):
        add("B_PLANO_PESSOAL", "papéis com plano pessoal: " + ", ".join(ctx["planos_pessoais"]), len(ctx["planos_pessoais"]))
    rev = ctx.get("revisao") or {}
    if rev.get("alto"):
        add("B_REVISAO_ALTO", f"{len(rev['alto'])} apontamento(s) [ALTO] da revisão", len(rev["alto"]))
    # ---- C
    if rev.get("melhorias"):
        add("C_REVISAO_MELHORIAS", f"{len(rev['melhorias'])} sugestão(ões) da revisão", len(rev["melhorias"]))
    if rev.get("desempenho"):
        add("C_REVISAO_DESEMPENHO", f"{len(rev['desempenho'])} apontamento(s)", len(rev["desempenho"]))
    if rev.get("divida"):
        add("C_REVISAO_DIVIDA", f"{len(rev['divida'])} apontamento(s)", len(rev["divida"]))
    t = ctx.get("tamanho") or {}
    if t.get("linhas", 0) > int(rc.get("alteracao_grande_linhas", 800)):
        add("C_ALTERACAO_GRANDE", f"{t['linhas']} linhas alteradas em {t.get('arquivos')} arquivo(s)")
    if ctx.get("ca_nao_must_nao_atendidos"):
        add("C_CRITERIO_NAO_ATENDIDO", "critérios: " + ", ".join(ctx["ca_nao_must_nao_atendidos"]), len(ctx["ca_nao_must_nao_atendidos"]))
    # ---- não verificado
    if ctx.get("passos_nao_rodados"):
        add("NV_PASSOS_NAO_RODADOS", "não rodaram: " + ", ".join(ctx["passos_nao_rodados"]))
    if ctx.get("mutacao_nao_rodada"):
        add("NV_MUTACAO_NAO_RODADA", "o passo MUTACAO não rodou")
    if ctx.get("gasto_nao_medido"):
        add("NV_GASTO_NAO_MEDIDO", "sem custo informado em: " + ", ".join(ctx["gasto_nao_medido"]))
    add("NV_DADO_REAL_PADROES", "varredura por padrões de CPF e e-mail nas linhas acrescentadas")
    # mitigação que não adiantou: o risco continua e o texto diz isso
    for it in out:
        if it["chave"] in (ctx.get("mitigacao_nao_eficaz") or []):
            it["evidencia"] += " | mitigação tentada e não eficaz"
    out.sort(key=lambda i: (ORDEM_NIVEL[i["nivel"]], i["chave"]))
    for n, it in enumerate(out, 1):
        it["id"] = f"R-{n:02d}"
    return out


def hash_lista(itens: list[dict]) -> str:
    return sha256(core.canonico([[i["chave"], i["nivel"], i["evidencia"]] for i in itens]))


def texto_exato(i: dict) -> str:
    """O texto que o PO aceita e que vai para o registro: o do catálogo mais a evidência."""
    return f"[{i['nivel']}] {i['titulo']}. {i['texto']} Evidência: {i['evidencia']}."


def texto_lista(itens: list[dict]) -> str:
    return "\n".join(f"{i['id']} | nível {i['nivel']} | {i['regra']} | {i['titulo']} | {i['evidencia']}"
                     + (f" | consultar: {', '.join(i['consultar'])}" if i["nivel"] == "B" and i["consultar"] else "")
                     for i in itens) or "(lista vazia)"


def calcular(repo: str, tarefa_dir: str, cfg: dict, base: str = "origin/main") -> dict:
    """Dados do evento RISCOS_LISTADOS."""
    st = core.estado(tarefa_dir, cfg)
    ctx = coletar_contexto(repo, tarefa_dir, cfg, st, base)
    itens = classificar(ctx, cfg)
    return {"itens": itens, "hash_lista": hash_lista(itens), "hash_codigo": core.hash_codigo(repo),
            "a": sum(1 for i in itens if i["nivel"] == "A"), "contexto_sha256": sha256(core.canonico(ctx))}


# ----------------------------------------------------------------------------- declaração e relatório
def ler_declaracao(texto: str, cfg: dict) -> dict:
    """Nível B: 'consultei: <área>; <nome e cargo>; <data>[; resumo opcional][; anexo: ...]'."""
    m = re.match(r"consultei\s*:\s*(.+)$", (texto or "").strip(), re.S | re.I)
    if not m:
        raise ErroFL("risco de nível B exige a declaração de quem foi consultado: "
                     "/s2r aceitar R-xx consultei: <área>; <nome e cargo>; <data>[; resumo da orientação]")
    partes = [x.strip() for x in m.group(1).split(";") if x.strip()]
    if len(partes) < 3:
        raise ErroFL("declaração incompleta: são obrigatórios a área consultada, o nome e o cargo de quem orientou e a data")
    area, nome_cargo, data = partes[0], partes[1], partes[2]
    if not re.search(r"[A-Za-zÀ-ú]{2,}.*,.*[A-Za-zÀ-ú]{2,}", nome_cargo):
        raise ErroFL("diga o nome e o cargo de quem orientou, separados por vírgula (ex.: Maria Silva, gerente de SegInfo)")
    if not re.fullmatch(r"(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})", data):
        raise ErroFL("a data da consulta deve ser dd/mm/aaaa ou aaaa-mm-dd")
    resto = partes[3:]
    anexo = next((x for x in resto if x.lower().startswith("anexo")), None)
    resumo = " ".join(x for x in resto if x is not anexo)[:2000] or None
    if (cfg.get("aceite") or {}).get("exigir_anexo_B") and not anexo:
        raise ErroFL("este repositório exige parecer anexado no nível B: acrescente '; anexo: <link ou id do parecer>'")
    return {"area": area[:100], "nome_cargo": nome_cargo[:200], "data": data, "decisao_po": "ACEITO",
            "resumo": resumo, "anexo": anexo}


def ler_relatorio(md: str, itens: list[dict]) -> None:
    """Confere o relatório da IA contra a lista do código: cobre todos, não muda nível, não inventa."""
    if not md.strip():
        raise ErroFL("relatorio-riscos.md ausente ou vazio")
    if len(md) > 20000:
        raise ErroFL("relatorio-riscos.md passa de 20000 caracteres: seja mais curto, quem lê não é programador")
    por_id = {i["id"]: i for i in itens}
    secoes = {m.group(1): m for m in re.finditer(r"^##\s+(R-\d+)\b.*$", md, re.M)}
    inventados = sorted(set(re.findall(r"\bR-\d+\b", md)) - set(por_id))
    if inventados:
        raise ErroFL("o relatório cita risco que a lista não tem: " + ", ".join(inventados))
    faltam = [i for i in por_id if i not in secoes]
    if faltam:
        raise ErroFL("o relatório não cobre estes riscos da lista (um '## R-xx título' para cada): " + ", ".join(faltam))
    marcas = sorted(secoes.values(), key=lambda m: m.start())
    for n, m in enumerate(marcas):
        fim = marcas[n + 1].start() if n + 1 < len(marcas) else len(md)
        trecho = md[m.start():fim]
        # a última seção de risco termina na primeira seção fixa
        corte = re.search(r"^##\s+(?!R-\d)", trecho[3:], re.M)
        if corte:
            trecho = trecho[:corte.start() + 3]
        niv = re.search(r"^Nível:\s*([ABC])\s*$", trecho, re.M)
        rid = m.group(1)
        if not niv or niv.group(1) != por_id[rid]["nivel"]:
            raise ErroFL(f"{rid}: a linha 'Nível: {por_id[rid]['nivel']}' é obrigatória e não pode ser mudada pela IA")
        if not re.search(r"Prós", trecho) or not re.search(r"Contras", trecho):
            raise ErroFL(f"{rid}: faltam os prós e os contras de aceitar")
    for titulo in ("O que não foi verificado", "Custo de não seguir adiante (estimativa da IA)"):
        if not re.search(rf"^##\s+{re.escape(titulo)}\s*$", md, re.M):
            raise ErroFL(f"relatório sem a seção '## {titulo}'")
    nv = [i["id"] for i in itens if i["regra"].startswith("NV_")]
    sec = re.search(r"^##\s+O que não foi verificado\s*$(.*?)(?=^##\s|\Z)", md, re.M | re.S)
    nao_citados = [i for i in nv if not (sec and re.search(rf"\b{i}\b", sec.group(1)))]
    if nao_citados:
        raise ErroFL("a seção 'O que não foi verificado' precisa citar: " + ", ".join(nao_citados))


# ----------------------------------------------------------------------------- roteiro, mitigação, painel
def roteiro(repo: str, tarefa_dir: str, cfg: dict) -> list[dict]:
    """Roteiro de aceite gerado por código: um item por critério da SPEC aprovada."""
    s = core.spec_da_tarefa(repo, tarefa_dir, cfg)
    md = ler(os.path.join(tarefa_dir, "spec.md"))
    must = set(s.cas_must())
    out = []
    for ca in sorted(s.cas):
        m = re.search(rf"^- {re.escape(ca)}\b\s*(?:\([^)]*\))?\s*(.*)$", md, re.M)
        out.append({"id": ca, "must": ca in must, "texto": (m.group(1).strip() if m else "")[:400]})
    return out


def texto_roteiro(cas: list[dict], url: str | None, instrucao: str, modo: str) -> str:
    cab = {"docker_local": "Rode a prévia no seu notebook (Docker) e confira que é o commit desta tarefa com: python -P -m spec2run previa-local",
           "homologacao": "Abra a prévia em homologação"}[modo]
    linhas = [f"**Roteiro de aceite** ({cab})" + (f": {url}" if url else "") + (f"\n\nComando: `{instrucao}`" if instrucao else "")]
    linhas += [f"- [{'MUST' if c['must'] else 'opcional'}] **{c['id']}**: {c['texto']}" for c in cas]
    linhas.append("\nPara cada critério comente, por exemplo:\n```\n" + "\n".join(
        f"/s2r aceite {c['id']} atende" for c in cas[:6]) + "\n```\nSe algo não atende: `/s2r aceite <CA> nao-atende defeito <o que viu>` "
        "(volta ao construtor) ou `/s2r aceite <CA> nao-atende requisito <o que esperava>` (volta à especificação).")
    return "\n".join(linhas)


def verificar_mitigacao(repo: str, tarefa_dir: str, cfg: dict, base: str = "origin/main") -> tuple[dict, dict]:
    """(dados RISCOS_LISTADOS, dados MITIGACAO_VERIFICADA). O risco só some se a REGRA o deixar de achar."""
    st = core.estado(tarefa_dir, cfg)
    lista = calcular(repo, tarefa_dir, cfg, base)
    lista["mitigacao"] = True
    atuais = {i["chave"]: i for i in lista["itens"]}
    restantes = []
    for ch in st.alvo_mitigacao:
        antes = next((i for i in st.riscos_itens if i["chave"] == ch), None)
        agora = atuais.get(ch)
        if agora is None:
            continue
        if antes is None or ORDEM_NIVEL[agora["nivel"]] <= ORDEM_NIVEL[antes["nivel"]]:
            restantes.append(ch)  # continua igual ou pior (A vem antes de B e de C)
    for ch, i in atuais.items():
        if i["nivel"] == "A":
            restantes.append(ch) if ch not in restantes else None
    ok = not restantes
    return lista, {"ok": ok, "restantes": restantes, "tentativa": st.mitigacoes + 1,
                   "riscos_antes": st.alvo_mitigacao, "hash_lista": lista["hash_lista"]}


def painel(repo: str, cfg: dict) -> str:
    """Painel de riscos aceitos, gerado só do registro de todas as tarefas."""
    raiz = os.path.join(repo, ".spec2run", "tarefas")
    linhas, abertas = [], []
    if os.path.isdir(raiz):
        for n in sorted(os.listdir(raiz), key=lambda x: (len(x), x)):
            d = os.path.join(raiz, n)
            if not os.path.isfile(os.path.join(d, "registro.jsonl")):
                continue
            st = core.estado(d, cfg)
            for e in core.Registro(d).eventos():
                if e["evento"] == "DECISAO" and e["dados"].get("acao") in ("ACEITAR_RISCOS", "ACEITAR_RISCO"):
                    for r in e["dados"].get("riscos", []):
                        decl = e["dados"].get("declaracao")
                        linhas.append((n, r["nivel"], r["regra"], e["dados"].get("nome", e["dados"]["autor"]), e["em"][:10],
                                       (f"consultou {decl['area']} ({decl['nome_cargo']}, {decl['data']})" if decl else "sem consulta (nível C)"),
                                       e["dados"].get("hash_codigo", "")[:12]))
            pend = [i for i in st.riscos_itens if i["nivel"] != "A" and i["chave"] not in st.aceitos]
            if st.fase == "RISCOS" and pend:
                abertas.append((n, ", ".join(f"{i['id']} ({i['nivel']})" for i in pend)))
            if st.fase == "RISCO_A":
                abertas.append((n, "risco de nível A bloqueando"))
    out = ["## Painel de riscos aceitos (Spec2Run 1.4)", "",
           "| Tarefa | Nível | Regra | Aceito por | Data | Consulta | Versão do código |", "|---|---|---|---|---|---|---|"]
    out += [f"| #{a} | {b} | {c} | {d} | {e} | {f} | `{g}` |" for a, b, c, d, e, f, g in linhas] or ["| (nenhum) | | | | | | |"]
    out += ["", "**Em aberto:** " + ("; ".join(f"#{n}: {t}" for n, t in abertas) if abertas else "nada")]
    return "\n".join(out)


def mensagem_riscos(tarefa_dir: str, st: "core.Estado") -> str:
    """Comentário do gate RISCOS: relatório da IA (explicação) mais a lista que o código montou (a verdade)."""
    c = os.path.join(tarefa_dir, "relatorio-riscos.md")
    rel = ler(c)[:30000] if os.path.exists(c) else "(o RISK_REPORTER não entregou relatório)"
    tabela = ["| Id | Nível | O que é | Evidência (da máquina) | Consultar (nível B) |", "|---|---|---|---|---|"]
    tabela += [f"| {i['id']} | {i['nivel']} | {i['titulo']} | {i['evidencia']} | "
               f"{', '.join(i['consultar']) if i['nivel'] == 'B' else '-'} |" for i in st.riscos_itens]
    return ("\n\n**Lista de riscos (montada e classificada por código, não pela IA):**\n\n" + "\n".join(tabela)
            + "\n\n**Relatório em linguagem simples (escrito pela IA; a lista acima prevalece):**\n\n" + rel)
