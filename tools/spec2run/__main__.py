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

from . import core
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


def mensagem(nx: dict, st: core.Estado) -> str:
    """Texto do comentário na issue: o que aconteceu e o que a pessoa precisa fazer."""
    if nx["tipo"] == "HUMANO":
        txt = f"**Spec2Run Light, sua vez ({nx['gate']}):** {nx['pedido']}"
        cola = {"L1": "/s2r aprovar", "TESTES": "/s2r aprovar testes", "L4": "/s2r aprovar codigo",
                "BLOQUEIO": "/s2r retomar"}.get(nx["gate"])
        if cola:
            txt += f"\n\nPara seguir, copie e cole como comentário nesta issue:\n```\n{cola}\n```"
        if st.feedback:
            txt += f"\n\nÚltimo retorno:\n```\n{st.feedback[:3000]}\n```"
        return txt
    if nx["tipo"] == "FIM":
        return f"**Spec2Run Light:** {nx['motivo']}."
    if nx["tipo"] == "AGENTE":
        return f"Spec2Run Light: próxima etapa {nx['papel']} ({nx['alvo']}), tentativa {nx['tentativa']}."
    return f"Spec2Run Light: próxima etapa de máquina {nx['etapa']} ({nx['descricao']})."


def cmd_estado(args):
    nx, _, st = _proxima(args)
    _, d = _tarefa(args)
    nx["fase"] = st.fase
    if args.formato == "github":
        _saida_github({k: v for k, v in nx.items() if k != "feedback"})
        if args.mensagem_arquivo:
            with open(args.mensagem_arquivo, "w", encoding="utf-8") as f:
                f.write(mensagem(nx, st) + (core.texto_l4(d, st) if nx.get("gate") == "L4" else ""))
    else:
        print(json.dumps(nx, ensure_ascii=False, indent=2))


def cmd_prompt(args):
    nx, cfg, _ = _proxima(args)
    if nx["tipo"] != "AGENTE":
        raise ErroFL(f"nenhum agente a acionar agora ({nx['tipo']})")
    _, d = _tarefa(args)
    diff = core.ler(args.diff_arquivo) if args.diff_arquivo else None
    sys.stdout.write(core.montar_prompt(args.repo, d, nx["papel"], nx["alvo"], cfg, diff))


def cmd_aceitar_entrega(args):
    """Roda no job de publicação, com a entrega do agente já aplicada na árvore.

    Se a entrega for recusada, a árvore volta ao commit anterior antes de registrar a
    recusa: o que o agente escreveu fora das regras nunca chega à branch.
    """
    nx, cfg, _ = _proxima(args)
    if nx["tipo"] != "AGENTE":
        raise ErroFL(f"nenhuma entrega esperada agora ({nx['tipo']})")
    rel, d = _tarefa(args)
    papel, alvo = nx["papel"], nx["alvo"]
    _git(args.repo, "add", "-A")
    raw = _git(args.repo, "diff", "--cached", "--raw", "--no-renames")
    try:
        saida = None
        if args.saida_agente and os.path.isfile(args.saida_agente):
            saida = core.ler(args.saida_agente)
        erro_cli, credencial = core.diagnosticar_saida_cli(saida)
        if erro_cli:
            raise core.ErroAgente(f"{papel}: {erro_cli}", credencial)
        caminhos = core.checar_escopo(raw, papel, alvo, rel, cfg)
        if papel in ("BUILDER", "TEST_DESIGNER"):
            core.checar_marcadores(_git(args.repo, "diff", "--cached", "-U0", "--no-renames", "--no-color"), papel, cfg)
        if papel == "BUILDER":
            core.checar_campos_protegidos(caminhos, lambda c: _mostrar(args.repo, "HEAD", c),
                                          lambda c: _mostrar(args.repo, "", c), cfg)
        dados = core.checar_entrega(args.repo, d, papel, alvo, cfg)
        if papel == "TEST_DESIGNER":
            dados["testes_modificados"] = core.testes_modificados(raw, cfg)
        if papel == "REVIEWER" and alvo == "codigo":
            _, nao_lidos, n = core.preparar_diff(_diff_tarefa(args.repo, args.base), cfg["testes"]["globs"])
            dados.update({"diff_caracteres": n, "diff_cortado": bool(nao_lidos), "arquivos_nao_lidos": nao_lidos[:30]})
        dados.update({"papel": papel, "alvo": alvo, "arquivos_alterados": caminhos,
                      "fornecedor": nx["fornecedor"], "modelo": nx["modelo"], "tentativa": nx["tentativa"]})
        core.Registro(d).anexar("ENTREGA_ACEITA", dados)
        print(f"entrega de {papel} aceita")
    except ErroFL as e:
        _git(args.repo, "reset", "-q", "--hard", "HEAD")
        _git(args.repo, "clean", "-fdq")
        if not core.Registro(d).eventos():
            raise ErroFL("registro.jsonl não está no último commit da branch: a máquina precisa commitar cada etapa")
        core.Registro(d).anexar("ENTREGA_RECUSADA", {"papel": papel, "alvo": alvo, "motivo": str(e)[:6000],
                                                     "credencial": bool(getattr(e, "credencial", False)),
                                                     "fornecedor": nx["fornecedor"], "tentativa": nx["tentativa"]})
        print(f"entrega de {papel} recusada:\n{e}")
        sys.exit(3)


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
    p = novo("iniciar", cmd_iniciar)
    for a in ("--pedido-arquivo", "--autor", "--rotulador"):
        p.add_argument(a, required=True)
    p = novo("comandos", cmd_comandos)
    p.add_argument("--arquivo", required=True)
    p.add_argument("--recusas-arquivo")
    p = novo("estado", cmd_estado)
    p.add_argument("--formato", choices=("json", "github"), default="json")
    p.add_argument("--mensagem-arquivo")
    novo("prompt", cmd_prompt).add_argument("--diff-arquivo")
    p = novo("aceitar-entrega", cmd_aceitar_entrega)
    p.add_argument("--base", default="origin/main")
    p.add_argument("--saida-agente")
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
    args = ap.parse_args(argv)
    try:
        args.f(args)
    except ErroFL as e:
        print(f"ERRO: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
