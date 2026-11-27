"""CLI do Spec2Run Light. Uso: python -P -m spec2run <comando> --repo <dir> --tarefa <n> ...

Sempre com -P: sem ele o Python procura módulos primeiro na pasta atual, que é a branch da
tarefa, onde um agente poderia ter deixado um json.py ou um spec2run/ falso.

Cada comando é um passo pequeno e determinístico chamado pelo workflow. O papel e o alvo
nunca vêm de fora: são sempre recalculados a partir do registro da tarefa, para que um
disparo manual ou um evento repetido não consiga pular etapa.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

from . import core, riscos
from .core import ErroFL

RAIZ_TAREFAS = ".spec2run/tarefas"


def _git(repo: str, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def _tarefa(args) -> tuple[str, str]:
    # A tarefa é o número da issue. Só dígitos: o valor vira caminho de pasta e nome de branch.
    if not re.fullmatch(r"\d{1,9}", str(args.tarefa)):
        raise ErroFL(f"tarefa inválida: {args.tarefa!r} (use o número da issue)")
    rel = f"{RAIZ_TAREFAS}/{args.tarefa}"
    return rel, os.path.join(args.repo, rel)


def _saida_github(d: dict) -> None:
    destino = os.environ.get("GITHUB_OUTPUT")
    linhas = [f"{k}={v}" for k, v in d.items() if isinstance(v, (str, int)) and "\n" not in str(v)]
    if destino:
        with open(destino, "a", encoding="utf-8") as f:
            f.write("\n".join(linhas) + "\n")
    else:
        print("\n".join(linhas))


def cmd_checar_config(args):
    cfg = core.carregar_config(args.repo)
    for a in core.avisos_config(cfg):
        print(a)
    print("config.json válido")


def cmd_verificar_ordem_ci(args):
    """Na instalação: a ordem dos passos do GREEN tem de ser a do CI do repositório (DL-60).
    Procura o comando de cada passo no arquivo do CI e confere se a sequência é a mesma."""
    cfg = core.carregar_config(args.repo)
    if core.fluxo(cfg) != "1.4":
        print("verificação da ordem do CI só vale no fluxo 1.4")
        return
    ci = cfg.get("ci_do_repositorio")
    if not ci:
        raise ErroFL("sem ci_do_repositorio no config.json: não há CI para comparar")
    caminho = os.path.join(args.repo, ".github", "workflows", ci)
    if not os.path.isfile(caminho):
        raise ErroFL(f"o CI {ci} não existe em .github/workflows")
    texto = re.sub(r"\s+", " ", core.ler(caminho))
    achados, ausentes = [], []
    for nome in core.ordem_green(cfg, "ELEVADO"):
        cmd = ((cfg["comandos"].get(nome) or {}).get("cmd") or "").strip()
        if not cmd:
            continue
        pos = texto.find(re.sub(r"\s+", " ", cmd))
        (achados if pos >= 0 else ausentes).append((pos, nome))
    erros = []
    ordem_ci = [n for _, n in sorted(achados)]
    ordem_cfg = [n for _, n in achados]
    if ordem_ci != ordem_cfg:
        erros.append(f"ordem diferente: o CI roda {' > '.join(ordem_ci)}; o GREEN roda {' > '.join(ordem_cfg)}. "
                     "Ajuste green_ordem no config.json (a main) ou o CI, para serem iguais")
    for _, n in ausentes:
        print(f"AVISO: o comando de {n} não aparece literalmente no CI; confira à mão se a posição dele é a mesma")
    if erros:
        raise ErroFL("\n".join(erros))
    print(f"ordem do GREEN confere com o CI ({ci}): " + " > ".join(ordem_cfg))


def cmd_iniciar(args):
    cfg = core.carregar_config(args.repo)
    rel, d = _tarefa(args)
    # O corpo da issue vira prompt dos agentes. Só vale pedido escrito E marcado por alguém de
    # 'humanos': num repositório público qualquer pessoa abre issue.
    for quem, papel in ((args.autor, "autor da issue"), (args.rotulador, "quem marcou a issue")):
        if quem not in cfg["humanos"]:
            raise ErroFL(f"{papel} (@{quem}) não está em 'humanos' do config.json: a tarefa não foi iniciada")
    if core.Registro(d).eventos():
        print(f"tarefa {args.tarefa} já iniciada"); return
    os.makedirs(d, exist_ok=True)
    pedido = core.ler(args.pedido_arquivo)
    with open(os.path.join(d, "pedido.md"), "w", encoding="utf-8") as f:
        texto = pedido.strip()
        if len(texto) > core.MAX_PEDIDO:
            texto = texto[:core.MAX_PEDIDO] + "\n\n[pedido cortado: divida a tarefa]"
        f.write(f"# Pedido (issue #{args.tarefa})\n\n{texto}\n")
    core.Registro(d).anexar("TAREFA_CRIADA", {"issue": int(args.tarefa), "versao": core.VERSAO,
                                               "config_sha256": core.sha256(core.canonico(cfg))})
    print(f"tarefa {args.tarefa} criada em {rel}")


def _proxima(args) -> tuple[dict, dict, core.Estado]:
    cfg = core.carregar_config(args.repo)
    _, d = _tarefa(args)
    if not core.Registro(d).eventos():
        raise ErroFL(f"tarefa {args.tarefa} não iniciada: marque a issue com o rótulo spec2run")
    st = core.estado(d, cfg)
    nx = st.proxima()
    if nx["tipo"] == "AGENTE":
        nx.update(core.rota(cfg, nx["papel"]))
    return nx, cfg, st


def proximos_comandos(nx: dict, st: core.Estado) -> str:
    """Comandos prontos para copiar e colar em cada ponto de decisão (DL-60: o PO nunca usa terminal)."""
    g = nx.get("gate")
    if g == "L1":
        return "/s2r aprovar\n\nSe não concordar:\n/s2r rejeitar spec <o que mudar>"
    if g == "TESTES":
        return "/s2r aprovar testes"
    if g == "L4":
        return "/s2r aprovar codigo\n\nSe não concordar:\n/s2r rejeitar codigo <motivo>"
    if g == "BLOQUEIO":
        return "/s2r retomar\n\nOu, para encerrar a tarefa:\n/s2r cancelar"
    if g == "ACEITE":
        ids = [c["id"] for c in st.cas] or ["CA-001"]
        return ("\n".join(f"/s2r aceite {i} atende" for i in ids) +
                "\n\nSe algum não atender, troque a linha por uma destas:\n"
                "/s2r aceite <CA> nao-atende defeito <o que você viu>\n/s2r aceite <CA> nao-atende requisito <o que você esperava>")
    if g == "RISCOS":
        b = [i["id"] for i in st.riscos_itens if i["nivel"] == "B" and i["chave"] not in st.aceitos]
        linhas = ["/s2r aceitar riscos          (aceita todos os de nível C)"]
        linhas += [f"/s2r aceitar {i} consultei: <área>; <nome e cargo>; <dd/mm/aaaa>" for i in b]
        linhas += ["", "Se não quiser aceitar um risco (a IA tenta mitigar):", "/s2r nao-aceitar <R-xx> <motivo>"]
        return "\n".join(linhas)
    if g == "RISCO_A":
        return "/s2r rejeitar codigo <o que corrigir>\n\nOu, para encerrar a tarefa:\n/s2r cancelar"
    if g == "MITIGACAO":
        return "/s2r seguir\n\nOu, para encerrar a tarefa:\n/s2r cancelar"
    if g == "TETO":
        esc = (st.teto or {}).get("escopo")
        if esc == "tarefa_chamadas":
            return "/s2r limite <novo total de chamadas, por exemplo 40>\n\nOu, para encerrar a tarefa:\n/s2r cancelar"
        return "/s2r limite <novo limite em US$, por exemplo 5>\n/s2r aguardar\n\n(escolha uma das duas)"
    if g == "ESCOPO":
        return "/s2r cancelar"
    return ""


def mensagem(nx: dict, st: core.Estado) -> str:
    """Texto do comentário na issue: o que aconteceu e o que a pessoa precisa fazer."""
    if nx["tipo"] == "HUMANO":
        txt = f"**Spec2Run Light, sua vez ({nx['gate']}):** {nx['pedido']}"
        cola = proximos_comandos(nx, st)
        if cola:
            txt += ("\n\nTudo se faz pelo navegador, comentando nesta issue. Copie, ajuste o que estiver entre < > e cole "
                    f"como comentário:\n```\n{cola}\n```")
        if st.feedback:
            txt += f"\n\nÚltimo retorno:\n```\n{st.feedback[:3000]}\n```"
        return txt
    if nx["tipo"] == "FIM":
        return f"**Spec2Run Light:** {nx['motivo']}."
    if nx["tipo"] == "AGENTE":
        return f"Spec2Run Light: próxima etapa {nx['papel']} ({nx['alvo']}), tentativa {nx['tentativa']}."
    if nx["tipo"] in ("LOCAL", "PREVIA"):
        return f"Spec2Run Light: próxima etapa {nx['etapa']} ({nx['descricao']})."
    return f"Spec2Run Light: próxima etapa de máquina {nx['etapa']} ({nx['descricao']})."


def cmd_estado(args):
    nx, _, st = _proxima(args)
    _, d = _tarefa(args)
    nx["fase"] = st.fase
    if args.formato == "github":
        _saida_github({k: v for k, v in nx.items() if k != "feedback"})
        if args.mensagem_arquivo:
            extra = ""
            if nx.get("gate") == "L4":
                extra = core.texto_l4(d, st)
            elif nx.get("gate") == "ACEITE":
                extra = "\n\n" + riscos.texto_roteiro(st.cas, st.previa_url, st.previa_instrucao, st.previa_modo)
            elif nx.get("gate") in ("RISCOS", "RISCO_A", "MITIGACAO"):
                extra = riscos.mensagem_riscos(d, st)
            with open(args.mensagem_arquivo, "w", encoding="utf-8") as f:
                f.write(mensagem(nx, st) + extra)
    else:
        print(json.dumps(nx, ensure_ascii=False, indent=2))


def cmd_prompt(args):
    nx, cfg, _ = _proxima(args)
    if nx["tipo"] != "AGENTE":
        raise ErroFL(f"nenhum agente a acionar agora ({nx['tipo']})")
    _, d = _tarefa(args)
    diff = core.ler(args.diff_arquivo) if args.diff_arquivo else None
    plano = json.loads(core.ler(args.plano_arquivo)) if args.plano_arquivo else None
    if args.parte and not plano:
        raise ErroFL("--parte exige --plano-arquivo")
    sys.stdout.write(core.montar_prompt(args.repo, d, nx["papel"], nx["alvo"], cfg, diff, plano, args.parte))


def _reviewer_codigo(args) -> tuple[dict, dict, core.Estado]:
    nx, cfg, st = _proxima(args)
    if not (nx["tipo"] == "AGENTE" and nx["papel"] == "REVIEWER" and nx["alvo"] == "codigo"):
        raise ErroFL(f"a revisão do código não é a próxima etapa ({nx.get('papel') or nx['tipo']})")
    return nx, cfg, st


def cmd_plano_revisao(args):
    """Antes da revisão do código: mede o diff real e decide se cabe numa chamada ou precisa de partes (DL-61).
    Escreve plano.json, diff-<n>.txt de cada parte e n_partes (1 = fluxo de sempre) na pasta de saída."""
    _, cfg, _ = _reviewer_codigo(args)
    plano = core.plano_revisao(_diff_tarefa(args.repo, args.base), cfg)
    os.makedirs(args.saida_dir, exist_ok=True)
    n = 1
    if plano and len(plano["partes"]) > 1:
        n = len(plano["partes"])
        for i, texto in enumerate(plano.pop("textos"), 1):
            with open(os.path.join(args.saida_dir, f"diff-{i}.txt"), "w", encoding="utf-8") as f:
                f.write(texto)
        with open(os.path.join(args.saida_dir, "plano.json"), "w", encoding="utf-8") as f:
            json.dump(plano, f, ensure_ascii=False, indent=1)
    with open(os.path.join(args.saida_dir, "n_partes"), "w", encoding="utf-8") as f:
        f.write(str(n))
    print(f"partes={n}" + (f" ({plano['total_caracteres']} caracteres, limite {plano['limite']} por parte)" if plano else ""))


def _usd_das_saidas(pasta: str | None) -> list[tuple[int, str]]:
    """[(n, texto)] das saídas da CLI de cada parte (arquivos saida-parte-<n>.json), em ordem."""
    if not pasta or not os.path.isdir(pasta):
        return []
    out = []
    for nome in os.listdir(pasta):
        m = re.fullmatch(r"saida-parte-(\d{1,2})\.json", nome)
        if m:
            out.append((int(m.group(1)), core.ler(os.path.join(pasta, nome))))
    return sorted(out)


def _orcamento_esgotado(cfg: dict, st: core.Estado, d: str, n_partes: int, saidas: list[tuple[int, str]]) -> dict | None:
    """Se o teto da tarefa impede a revisão em partes, devolve o TETO_ATINGIDO a registrar; senão None.
    Chamadas: a revisão precisa das n partes ou de nenhuma (parte lida sem as outras não aprova nada).
    Dólares: soma o custo já registrado e o das partes desta rodada."""
    livres = core.chamadas_livres(cfg, st, d)
    mx = st.chamadas_max or (cfg.get("limites") or {}).get("chamadas_por_tarefa")
    if livres is not None and not saidas and n_partes > livres:
        return {"escopo": "tarefa_chamadas", "chamadas": int(mx) - livres, "limite": int(mx),
                "motivo": f"a revisão em {n_partes} partes precisa de {n_partes} chamadas e restam {livres} das {mx} desta tarefa"}
    lim_t = st.limite_tarefa_usd or (cfg.get("orcamento") or {}).get("limite_por_tarefa_usd")
    gasto = core.gasto_da_tarefa(d) + sum(core.custo_da_saida(t) or 0 for _, t in saidas)
    if lim_t and gasto >= lim_t:
        return {"escopo": "tarefa_usd", "gasto": round(gasto, 4), "limite": lim_t,
                "motivo": f"gasto de US$ {gasto:.2f} nesta tarefa, limite de US$ {lim_t:.2f}"}
    return None


def cmd_parte_liberada(args):
    """Antes de cada chamada da revisão em partes: o teto da tarefa ainda permite? Sai com 4 se não (o workflow para)."""
    nx, cfg, st = _reviewer_codigo(args)
    _, d = _tarefa(args)
    plano = json.loads(core.ler(args.plano_arquivo))
    saidas = _usd_das_saidas(args.saidas_dir)
    t = _orcamento_esgotado(cfg, st, d, len(plano["partes"]), saidas if args.parte > 1 else [])
    if t:
        print(f"revisão em partes parada antes da parte {args.parte}: {t['motivo']}")
        sys.exit(4)
    print(f"parte {args.parte} liberada")


def cmd_parte_guardar(args):
    _, d = _tarefa(args)
    guardados = core.guardar_parte(d, args.parte)
    print(f"parte {args.parte}: guardado {', '.join(guardados) or 'nada (o REVIEWER não entregou)'}")


def cmd_aceitar_entrega(args):
    """Roda no job de publicação, com a entrega do agente já aplicada na árvore.

    Se a entrega for recusada, a árvore volta ao commit anterior antes de registrar a
    recusa: o que o agente escreveu fora das regras nunca chega à branch.
    """
    nx, cfg, st0 = _proxima(args)
    if nx["tipo"] != "AGENTE":
        raise ErroFL(f"nenhuma entrega esperada agora ({nx['tipo']})")
    rel, d = _tarefa(args)
    papel, alvo = nx["papel"], nx["alvo"]
    _git(args.repo, "add", "-A")
    raw = _git(args.repo, "diff", "--cached", "--raw", "--no-renames")
    v14 = core.fluxo(cfg) == "1.4"
    saida = None
    if args.saida_agente and os.path.isfile(args.saida_agente):
        saida = core.ler(args.saida_agente)
    # Revisão em partes (DL-61): o plano é recalculado aqui, do diff real; nada do plano vem do agente.
    plano = core.plano_revisao(_diff_tarefa(args.repo, args.base), cfg) if (v14 and papel == "REVIEWER" and alvo == "codigo") else None
    multi = bool(plano and len(plano["partes"]) > 1)
    saidas = _usd_das_saidas(args.saidas_partes) if multi else []
    if multi:
        faltam = [p["n"] for p in plano["partes"]
                  if not (os.path.isfile(core.arquivo_parte(d, "revisao-codigo.md", p["n"]))
                          and os.path.isfile(core.arquivo_parte(d, "parecer-l4.md", p["n"])))]
        teto = _orcamento_esgotado(cfg, st0, d, len(plano["partes"]), saidas) if faltam else None
        if teto:
            # O teto da tarefa parou a revisão: não é defeito da entrega, não gasta tentativa. O custo já feito fica registrado.
            _git(args.repo, "reset", "-q", "--hard", "HEAD")
            _git(args.repo, "clean", "-fdq")
            _custos_partes(args.repo, d, cfg, nx, saidas, plano)
            if not core.estado(d, cfg).teto:
                core.Registro(d).anexar("TETO_ATINGIDO", {"papel": papel, **teto})
            print(f"revisão em partes parada pelo teto da tarefa: {teto['motivo']}")
            return
    try:
        if multi:
            for n, txt in saidas:
                erro_cli, credencial = core.diagnosticar_saida_cli(txt)
                if erro_cli:
                    saida = txt
                    raise core.ErroAgente(f"{papel} (parte {n} de {len(plano['partes'])}): {erro_cli}", credencial)
        else:
            erro_cli, credencial = core.diagnosticar_saida_cli(saida)
            if erro_cli:
                raise core.ErroAgente(f"{papel}: {erro_cli}", credencial)
        caminhos = core.checar_escopo(raw, papel, alvo, rel, cfg)
        if papel in ("BUILDER", "TEST_DESIGNER"):
            core.checar_marcadores(_git(args.repo, "diff", "--cached", "-U0", "--no-renames", "--no-color"), papel, cfg)
        if papel == "BUILDER":
            core.checar_campos_protegidos(caminhos, lambda c: _mostrar(args.repo, "HEAD", c),
                                          lambda c: _mostrar(args.repo, "", c), cfg)
        consolidado = core.consolidar_revisao(d, plano) if multi else None
        dados = core.checar_entrega(args.repo, d, papel, alvo, cfg)
        if papel == "TEST_DESIGNER":
            dados["testes_modificados"] = core.testes_modificados(raw, cfg)
        if papel == "REVIEWER" and alvo == "codigo":
            if plano is not None:
                nao_lidos, n, lim = plano["nao_lidos"], plano["total_caracteres"], plano["limite"]
            else:
                lim = core.max_diff(cfg)
                _, nao_lidos, n = core.preparar_diff(_diff_tarefa(args.repo, args.base), cfg["testes"]["globs"], lim)
            dados.update({"diff_caracteres": n, "diff_limite": lim, "diff_cortado": bool(nao_lidos), "arquivos_nao_lidos": nao_lidos[:30]})
            if multi:
                usd = {n_: core.custo_da_saida(t) for n_, t in saidas}
                dados["partes"] = [dict(p, usd=usd.get(p["n"])) for p in consolidado["partes"]]
        dados.update({"papel": papel, "alvo": alvo, "arquivos_alterados": caminhos,
                      "fornecedor": nx["fornecedor"], "modelo": nx["modelo"], "tentativa": nx["tentativa"]})
        core.Registro(d).anexar("ENTREGA_ACEITA", dados)
        if v14:
            if multi:
                _custos_partes(args.repo, d, cfg, nx, saidas, plano)
            else:
                _custo_e_teto(args.repo, d, cfg, nx, saida)
        print(f"entrega de {papel} aceita" + (f" ({len(plano['partes'])} partes)" if multi else ""))
    except ErroFL as e:
        _git(args.repo, "reset", "-q", "--hard", "HEAD")
        _git(args.repo, "clean", "-fdq")
        if not core.Registro(d).eventos():
            raise ErroFL("registro.jsonl não está no último commit da branch: a máquina precisa commitar cada etapa")
        recusa = {"papel": papel, "alvo": alvo, "motivo": str(e)[:6000],
                  "credencial": bool(getattr(e, "credencial", False)),
                  "fornecedor": nx["fornecedor"], "tentativa": nx["tentativa"]}
        if v14 and isinstance(e, core.ErroAgente) and core.eh_teto_gasto(saida or str(e)):
            recusa["teto"] = True   # o fornecedor disse que o crédito ou a cota acabou: sinal real de teto de gasto
        core.Registro(d).anexar("ENTREGA_RECUSADA", recusa)
        if v14:
            if multi:
                _custos_partes(args.repo, d, cfg, nx, saidas, plano)
            else:
                _custo_e_teto(args.repo, d, cfg, nx, saida)
        print(f"entrega de {papel} recusada:\n{e}")
        sys.exit(3)


def _custo_e_teto(repo: str, d: str, cfg: dict, nx: dict, saida: str | None) -> None:
    """1.4: registra o custo que a CLI informa (None se não informa) e para a tarefa se o limite do
    ciclo foi atingido. Só mede o que a CLI informa: o resto é 'gasto não medido' no relatório."""
    usd = core.custo_da_saida(saida)
    core.Registro(d).anexar("CUSTO", {"papel": nx["papel"], "fornecedor": nx["fornecedor"], "modelo": nx["modelo"], "usd": usd})
    _checar_teto(repo, d, cfg, nx, usd)


def _custos_partes(repo: str, d: str, cfg: dict, nx: dict, saidas: list[tuple[int, str]], plano: dict) -> None:
    """Revisão em partes (DL-61): um evento CUSTO por chamada (cada parte conta como chamada no teto da tarefa), com
    o número da parte; depois confere os tetos uma vez. Cada parte a mais custa uma chamada, também para quem não informa US$."""
    ultimo = None
    for n, txt in saidas:
        usd = core.custo_da_saida(txt)
        ultimo = usd if usd is not None else ultimo
        core.Registro(d).anexar("CUSTO", {"papel": nx["papel"], "fornecedor": nx["fornecedor"], "modelo": nx["modelo"],
                                         "usd": usd, "parte": n, "partes": len(plano["partes"])})
    _checar_teto(repo, d, cfg, nx, ultimo)


def _checar_teto(repo: str, d: str, cfg: dict, nx: dict, usd: float | None) -> None:
    papel = nx["papel"]
    st = core.estado(d, cfg)
    if st.teto:
        return
    # Teto por TAREFA (1.4, DL-60): protege uma tarefa em laço de consumir o ciclo inteiro. Chamadas valem para todo
    # fornecedor; dólares só onde a CLI informa o custo.
    evs = [e["dados"] for e in core.Registro(d).eventos() if e["evento"] == "CUSTO"]
    chamadas = len(evs)
    max_ch = st.chamadas_max or (cfg.get("limites") or {}).get("chamadas_por_tarefa")
    if max_ch and chamadas >= max_ch:
        core.Registro(d).anexar("TETO_ATINGIDO", {"papel": papel, "escopo": "tarefa_chamadas", "chamadas": chamadas, "limite": max_ch,
                                                 "motivo": f"{chamadas} chamadas de IA nesta tarefa, limite de {max_ch}"})
        return
    lim_t = st.limite_tarefa_usd or (cfg.get("orcamento") or {}).get("limite_por_tarefa_usd")
    gasto_t = round(sum(float(x["usd"]) for x in evs if x.get("usd") is not None), 4)
    if lim_t and gasto_t >= lim_t:
        core.Registro(d).anexar("TETO_ATINGIDO", {"papel": papel, "escopo": "tarefa_usd", "gasto": gasto_t, "limite": lim_t,
                                                 "motivo": f"gasto de US$ {gasto_t:.2f} nesta tarefa, limite de US$ {lim_t:.2f}"})
        return
    lim = core.limite_vigente(cfg, st, papel)
    if usd is None or lim is None:
        return
    gasto, _ = core.gasto_do_ciclo(repo, cfg, papel)
    if gasto >= lim:
        core.Registro(d).anexar("TETO_ATINGIDO", {"papel": papel, "gasto": gasto, "limite": lim, "escopo": "ciclo",
                                                 "motivo": f"gasto de US$ {gasto:.2f} no ciclo, limite de US$ {lim:.2f}"})


def _diff_tarefa(repo: str, base: str) -> str:
    """Diff da tarefa sem registro, evidências e lockfiles: o mesmo que o REVIEWER recebe."""
    return _git(repo, "diff", f"{base}...HEAD", "--", ".", *[f":(exclude){x}" for x in core.DIFF_EXCLUIR])


def cmd_diff_tarefa(args):
    with open(args.saida, "w", encoding="utf-8") as f:
        f.write(_diff_tarefa(args.repo, args.base))


def _mostrar(repo: str, rev: str, caminho: str) -> str | None:
    """Conteúdo do arquivo no commit rev, ou no índice (rev vazio). None se não existe."""
    p = subprocess.run(["git", "show", f"{rev}:{caminho}"], cwd=repo, capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else None


def cmd_evidencia(args):
    cfg = core.carregar_config(args.repo)
    _, d = _tarefa(args)
    st = core.estado(d, cfg)
    etapa = {"TESTES": "RED", "CODIGO": "GREEN"}.get(st.fase)
    if not etapa or st.bloqueio:
        raise ErroFL(f"nenhuma evidência de máquina esperada na fase {st.fase}")
    commit = _git(args.repo, "rev-parse", "HEAD").strip()
    ev = core.rodar_evidencia(args.repo, d, etapa, cfg, commit)
    with open(args.saida, "w", encoding="utf-8") as f:
        json.dump(ev, f, ensure_ascii=False, indent=2)
    ok, problemas = core.avaliar(etapa, ev["passos"], cfg, st.nivel, st.testes_red_total)
    print(f"{etapa}: {'ok' if ok else 'falhou'}" + "".join(f"\n- {p}" for p in problemas))


def cmd_registrar_evidencia(args):
    cfg = core.carregar_config(args.repo)
    _, d = _tarefa(args)
    ev = json.loads(core.ler(args.arquivo))
    commit = _git(args.repo, "rev-parse", "HEAD").strip()
    r = core.registrar_evidencia(args.repo, d, ev, cfg, commit)
    print(f"{r['etapa']} registrado: {'ok' if r['ok'] else 'falhou'}")


def _commit(repo: str) -> str:
    return _git(repo, "rev-parse", "HEAD").strip()


def cmd_local(args):
    """Etapa de código determinístico (sem agente, sem executar código da tarefa): roda no job que escreve."""
    nx, cfg, st = _proxima(args)
    if nx["tipo"] != "LOCAL":
        raise ErroFL(f"nenhuma etapa local agora ({nx['tipo']})")
    _, d = _tarefa(args)
    etapa, reg = nx["etapa"], core.Registro(d)
    if etapa == "PREVIA_LOCAL":
        cas = riscos.roteiro(args.repo, d, cfg)
        reg.anexar("PREVIA_PUBLICADA", {"modo": "docker_local", "commit": _commit(args.repo), "url": None, "cas": cas,
                                        "hash_codigo": core.hash_codigo(args.repo),
                                        "instrucao": (cfg["comandos"].get("PREVIA") or {}).get("cmd", "")})
    elif etapa == "CALCULAR_RISCOS":
        dados = riscos.calcular(args.repo, d, cfg, args.base)
        reg.anexar("RISCOS_LISTADOS", dados)
        print(f"{len(dados['itens'])} risco(s) listado(s); nível A: {dados['a']}")
    elif etapa == "VERIFICAR_MITIGACAO":
        lista, ver = riscos.verificar_mitigacao(args.repo, d, cfg, args.base)
        reg.anexar("RISCOS_LISTADOS", lista)
        reg.anexar("MITIGACAO_VERIFICADA", ver)
        print("mitigação " + ("confirmada pela regra de código" if ver["ok"] else "NÃO confirmada: " + ", ".join(ver["restantes"])))
    else:
        raise ErroFL(f"etapa local desconhecida: {etapa}")
    print(f"etapa local {etapa} registrada")


def cmd_previa(args):
    """Job com a credencial do Environment s2r-previa: publica a prévia e devolve o endereço."""
    nx, cfg, _ = _proxima(args)
    if nx["tipo"] != "PREVIA":
        raise ErroFL(f"nenhuma prévia a publicar agora ({nx['tipo']})")
    cmd = (cfg["comandos"].get("PREVIA") or {}).get("cmd")
    if not cmd:
        raise ErroFL("comandos.PREVIA.cmd vazio")
    timeout = int(cfg.get("limites", {}).get("timeout_comando_s", 900))
    passo = core._rodar("PREVIA", cmd, args.repo, timeout)
    urls = re.findall(r"https?://[^\s'\"<>]+", passo["saida_final"])
    with open(args.saida, "w", encoding="utf-8") as f:
        json.dump({"etapa": "PREVIA", "commit": _commit(args.repo), "hash_codigo": core.hash_codigo(args.repo),
                   "passos": [passo], "url": urls[-1] if urls else None, "em": core.agora()}, f, ensure_ascii=False, indent=2)
    print("prévia: " + ("ok" if passo["codigo_saida"] == 0 else "falhou"))


def cmd_registrar_previa(args):
    nx, cfg, _ = _proxima(args)
    if nx["tipo"] != "PREVIA":
        raise ErroFL(f"nenhuma prévia esperada agora ({nx['tipo']})")
    _, d = _tarefa(args)
    ev = json.loads(core.ler(args.arquivo))
    if ev.get("commit") != _commit(args.repo) or ev.get("hash_codigo") != core.hash_codigo(args.repo):
        raise ErroFL("a prévia não é do commit atual da branch: o código mudou depois de publicada")
    passo = ev["passos"][0]
    if passo["codigo_saida"] != 0:
        core.Registro(d).anexar("PREVIA_FALHOU", {"commit": ev["commit"], "resumo": passo["saida_final"][-500:]})
        print("prévia falhou; registrado")
        return
    cas = riscos.roteiro(args.repo, d, cfg)
    core.Registro(d).anexar("PREVIA_PUBLICADA", {"modo": cfg["previa"]["modo"], "commit": ev["commit"], "url": ev.get("url"),
                                                 "cas": cas, "hash_codigo": ev["hash_codigo"], "instrucao": ""})
    print("prévia registrada")


def cmd_previa_local(args):
    """No seu notebook: confere que o código local é o da prévia que a tarefa registrou e mostra o roteiro."""
    cfg = core.carregar_config(args.repo)
    _, d = _tarefa(args)
    st = core.estado(d, cfg)
    if st.fase != "ACEITE_PO":
        raise ErroFL(f"a tarefa está na fase {st.fase}; a prévia só vale na fase ACEITE_PO")
    if core.hash_codigo(args.repo) != st.previa_hash:
        raise ErroFL("o código desta pasta NÃO é o da prévia registrada. Traga a branch da tarefa "
                     f"(git fetch && git checkout s2r/tarefa-{args.tarefa} && git pull) e rode de novo")
    print("código conferido: é o da prévia desta tarefa.\n")
    print(riscos.texto_roteiro(st.cas, st.previa_url, st.previa_instrucao, st.previa_modo))


def cmd_painel(args):
    cfg = core.carregar_config(args.repo)
    txt = riscos.painel(args.repo, cfg)
    if args.saida:
        with open(args.saida, "w", encoding="utf-8") as f:
            f.write(txt + "\n")
    else:
        print(txt)


def cmd_decisao(args):
    cfg = core.carregar_config(args.repo)
    _, d = _tarefa(args)
    e = core.decidir(d, cfg, args.autor, args.associacao, core.ler(args.texto_arquivo), args.url)
    print("nenhum comando /s2r" if e is None else f"decisão registrada: {e['dados']['acao']}")


def cmd_comandos(args):
    """Lê os comentários /s2r da issue (JSON por linha, do gh api) e aplica os pendentes."""
    cfg = core.carregar_config(args.repo)
    _, d = _tarefa(args)
    if not core.Registro(d).eventos():
        return
    linhas = [l for l in core.ler(args.arquivo).splitlines() if l.strip()]
    msgs = core.processar_comentarios(d, cfg, [json.loads(l) for l in linhas])
    if args.recusas_arquivo and msgs:
        with open(args.recusas_arquivo, "w", encoding="utf-8") as f:
            f.write("**Spec2Run Light:** comando não aceito.\n\n" + "\n\n".join(f"```\n{m[:3000]}\n```" for m in msgs))
    print(f"{len(msgs)} comando(s) recusado(s)")


def cmd_verificar_pr(args):
    cfg = core.carregar_config(args.repo)
    _, d = _tarefa(args)
    st = core.estado(d, cfg)
    no_pr = _git(args.repo, "diff", "--name-only", "--no-renames", f"{args.base}...HEAD").split()
    desde_green = []
    if st.commit_green:
        desde_green = _git(args.repo, "diff", "--name-only", "--no-renames", st.commit_green, "HEAD").split()
        # DL-47: arquivo que só mudou porque a main foi trazida para a branch (o PR não o altera)
        # não é mudança da tarefa depois do GREEN.
        desde_green = core.so_do_pr(desde_green, no_pr)
    core.verificar_pr(args.repo, d, cfg, desde_green, no_pr)
    print("merge liberado")


def cmd_verificar(args):
    _, d = _tarefa(args)
    n = len(core.Registro(d).verificar())
    print(f"registro íntegro: {n} eventos")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="spec2run")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def novo(nome, f, tarefa=True):
        p = sub.add_parser(nome)
        p.add_argument("--repo", default=".")
        if tarefa:
            p.add_argument("--tarefa", required=True)
        p.set_defaults(f=f)
        return p

    novo("checar-config", cmd_checar_config, tarefa=False)
    novo("verificar-ordem-ci", cmd_verificar_ordem_ci, tarefa=False)
    p = novo("iniciar", cmd_iniciar)
    for a in ("--pedido-arquivo", "--autor", "--rotulador"):
        p.add_argument(a, required=True)
    p = novo("comandos", cmd_comandos)
    p.add_argument("--arquivo", required=True)
    p.add_argument("--recusas-arquivo")
    p = novo("estado", cmd_estado)
    p.add_argument("--formato", choices=("json", "github"), default="json")
    p.add_argument("--mensagem-arquivo")
    p = novo("prompt", cmd_prompt)
    p.add_argument("--diff-arquivo")
    p.add_argument("--plano-arquivo")
    p.add_argument("--parte", type=int)
    p = novo("plano-revisao", cmd_plano_revisao)
    p.add_argument("--base", default="origin/main")
    p.add_argument("--saida-dir", required=True)
    p = novo("parte-liberada", cmd_parte_liberada)
    p.add_argument("--parte", type=int, required=True)
    p.add_argument("--plano-arquivo", required=True)
    p.add_argument("--saidas-dir")
    novo("parte-guardar", cmd_parte_guardar).add_argument("--parte", type=int, required=True)
    p = novo("aceitar-entrega", cmd_aceitar_entrega)
    p.add_argument("--base", default="origin/main")
    p.add_argument("--saida-agente")
    p.add_argument("--saidas-partes", help="pasta com saida-parte-<n>.json da revisão em partes")
    p = novo("diff-tarefa", cmd_diff_tarefa)
    p.add_argument("--base", default="origin/main")
    p.add_argument("--saida", required=True)
    novo("evidencia", cmd_evidencia).add_argument("--saida", required=True)
    novo("registrar-evidencia", cmd_registrar_evidencia).add_argument("--arquivo", required=True)
    p = novo("decisao", cmd_decisao)
    for a in ("--autor", "--associacao", "--texto-arquivo", "--url"):
        p.add_argument(a, required=True)
    novo("verificar-pr", cmd_verificar_pr).add_argument("--base", default="origin/main")
    novo("verificar", cmd_verificar)
    novo("local", cmd_local).add_argument("--base", default="origin/main")
    novo("previa", cmd_previa).add_argument("--saida", required=True)
    novo("registrar-previa", cmd_registrar_previa).add_argument("--arquivo", required=True)
    novo("previa-local", cmd_previa_local)
    p = novo("painel", cmd_painel, tarefa=False)
    p.add_argument("--saida")
    args = ap.parse_args(argv)
    try:
        args.f(args)
    except ErroFL as e:
        print(f"ERRO: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
