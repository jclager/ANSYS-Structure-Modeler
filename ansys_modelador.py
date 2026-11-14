#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ansys_modelador.py
==================
Modelador interativo de estruturas no ANSYS Mechanical APDL (via PyMAPDL).

O programa faz perguntas sobre a estrutura/peça e, conforme as respostas,
escolhe sozinho o elemento finito (SHELL181, BEAM188, LINK180, SOLID186/187,
PLANE183), as KEYOPTs, a seção, o material, a malha, os apoios, as cargas e
o tipo de análise (estática, modal, flambagem linear, não linear e
flambagem elasto-plástica com imperfeição inicial).

Sempre gera um arquivo .mac (APDL puro) reproduzível e um .json com as
respostas. Se o ANSYS estiver instalado, executa o modelo e pós-processa.

Unidades: SI (m, N, Pa, kg/m³).

Uso:
    python ansys_modelador.py                    # questionário interativo
    python ansys_modelador.py --config arq.json  # reutiliza respostas salvas
    python ansys_modelador.py --somente-apdl     # só gera o .mac (sem ANSYS)

Licença: MIT
"""

import argparse
import datetime
import json
import math
import sys
import unicodedata
from pathlib import Path

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# Bibliotecas de dados
# ---------------------------------------------------------------------------
MATERIAIS = {
    "aco_a36":    {"nome": "Aço estrutural ASTM A36", "E": 200e9, "nu": 0.30, "rho": 7850, "fy": 250e6, "Et": 2.0e9},
    "aco_inox":   {"nome": "Aço inoxidável AISI 304", "E": 193e9, "nu": 0.29, "rho": 8000, "fy": 215e6, "Et": 2.0e9},
    "aluminio":   {"nome": "Alumínio 6061-T6",        "E": 68.9e9, "nu": 0.33, "rho": 2700, "fy": 276e6, "Et": 0.7e9},
    "concreto":   {"nome": "Concreto C30 (elástico)", "E": 31e9,  "nu": 0.20, "rho": 2500, "fy": None,  "Et": None},
    "madeira":    {"nome": "Madeira (isotrópica equivalente)", "E": 12e9, "nu": 0.30, "rho": 600, "fy": None, "Et": None},
}

TIPOS = {
    "placa":     ("Placa / chapa plana (com ou sem furo)",                "SHELL181"),
    "casca_cil": ("Casca cilíndrica (tubo de parede fina, tanque, torre)", "SHELL181"),
    "viga":      ("Viga / coluna / eixo (barra esbelta)",                  "BEAM188"),
    "trelica":   ("Treliça plana (barras articuladas, tipo Pratt)",        "LINK180"),
    "solido":    ("Bloco / peça maciça 3D (com ou sem furo passante)",     "SOLID186"),
    "plano":     ("Seção 2D: tensão plana, deformação plana ou axissimétrico", "PLANE183"),
}

ANALISES = {
    "estatica":     "Estática linear",
    "modal":        "Modal (frequências naturais)",
    "flambagem":    "Flambagem linear (autovalor)",
    "nao_linear":   "Não linear: plasticidade bilinear + grandes deslocamentos",
    "flambagem_nl": "Flambagem elasto-plástica: autovalor -> imperfeição (modo 1) -> não linear",
}


# ---------------------------------------------------------------------------
# Utilidades de entrada
# ---------------------------------------------------------------------------
def perguntar(msg, padrao=None, tipo=float, minimo=None):
    sufixo = f" [{padrao}]" if padrao is not None else ""
    while True:
        r = input(f"  {msg}{sufixo}: ").strip()
        if not r and padrao is not None:
            return padrao
        if tipo is str:
            if r:
                return r
            continue
        try:
            v = tipo(float(r.replace(",", "."))) if tipo is int else tipo(r.replace(",", "."))
        except ValueError:
            print("    valor inválido.")
            continue
        if minimo is not None and v <= minimo:
            print(f"    o valor deve ser maior que {minimo}.")
            continue
        return v


def escolher(msg, opcoes, padrao=1):
    """opcoes: lista de (chave, descrição). Retorna a chave."""
    print(f"\n{msg}")
    for i, (_, d) in enumerate(opcoes, 1):
        print(f"   {i} - {d}")
    while True:
        r = input(f"  Opção [{padrao}]: ").strip() or str(padrao)
        if r.isdigit() and 1 <= int(r) <= len(opcoes):
            return opcoes[int(r) - 1][0]
        print("    opção inválida.")


def sim_nao(msg, padrao="n"):
    r = input(f"  {msg} (s/n) [{padrao}]: ").strip().lower() or padrao
    return r.startswith("s")


def g(x):
    """Número formatado para APDL."""
    return f"{x:.8g}"


def ascii_apdl(txt):
    t = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode()
    return t.replace(",", " ")[:70]


# ---------------------------------------------------------------------------
# Questionário
# ---------------------------------------------------------------------------
def assistente_tipo():
    print("\n--- Assistente: informe as 3 dimensões principais da peça (mesma unidade) ---")
    d = sorted([perguntar("Dimensão 1", minimo=0), perguntar("Dimensão 2", minimo=0),
                perguntar("Dimensão 3", minimo=0)], reverse=True)
    d1, d2, d3 = d
    if d1 / d2 >= 10:
        print("  -> Uma dimensão domina (>= 10x): elemento de linha.")
        return "trelica" if sim_nao("É um conjunto de barras articuladas (treliça)?") else "viga"
    if d3 / d2 <= 0.1:
        print("  -> Espessura <= 1/10 das outras dimensões: elemento de casca.")
        return "casca_cil" if sim_nao("A superfície é curva/cilíndrica (tubo, tanque)?") else "placa"
    print("  -> Peça robusta nas três direções: elemento sólido.")
    if sim_nao("A peça pode ser tratada em 2D (seção constante longa ou axissimétrica)?"):
        return "plano"
    return "solido"


def q_material(analise_nl):
    ops = [(k, f"{v['nome']}  (E={v['E']/1e9:g} GPa)") for k, v in MATERIAIS.items()]
    ops.append(("outro", "Outro (informar propriedades)"))
    k = escolher("Material:", ops)
    if k == "outro":
        m = {"nome": perguntar("Nome do material", "Material", str),
             "E": perguntar("Módulo de elasticidade E (Pa)", 200e9, minimo=0),
             "nu": perguntar("Coeficiente de Poisson", 0.3),
             "rho": perguntar("Densidade (kg/m³)", 7850.0, minimo=0),
             "fy": None, "Et": None}
    else:
        m = dict(MATERIAIS[k])
    if analise_nl and not m.get("fy"):
        print("  A análise não linear exige tensão de escoamento.")
        m["fy"] = perguntar("Tensão de escoamento fy (Pa)", 250e6, minimo=0)
        m["Et"] = perguntar("Módulo tangente Et (Pa)", m["E"] / 100, minimo=0)
    return m


def q_geometria(tipo):
    print("\nGeometria (m):")
    geo = {}
    if tipo == "placa":
        geo["a"] = perguntar("Comprimento a (direção X)", 1.0, minimo=0)
        geo["b"] = perguntar("Largura b (direção Y)", 0.5, minimo=0)
        geo["t"] = perguntar("Espessura t", 0.01, minimo=0)
        geo["furo"] = escolher("Furo na placa:", [("nenhum", "Sem furo"), ("circular", "Circular"),
                                                  ("retangular", "Retangular")])
        if geo["furo"] != "nenhum":
            geo["xc"] = perguntar("Centro do furo xc", geo["a"] / 2)
            geo["yc"] = perguntar("Centro do furo yc", geo["b"] / 2)
            if geo["furo"] == "circular":
                geo["d"] = perguntar("Diâmetro do furo", geo["b"] / 4, minimo=0)
            else:
                geo["wf"] = perguntar("Largura do furo (X)", geo["a"] / 4, minimo=0)
                geo["hf"] = perguntar("Altura do furo (Y)", geo["b"] / 4, minimo=0)
    elif tipo == "casca_cil":
        geo["R"] = perguntar("Raio médio R", 0.5, minimo=0)
        geo["L"] = perguntar("Comprimento L (eixo Z)", 2.0, minimo=0)
        geo["t"] = perguntar("Espessura t", 0.005, minimo=0)
    elif tipo == "viga":
        geo["L"] = perguntar("Comprimento L", 3.0, minimo=0)
        geo["secao"] = escolher("Seção transversal:", [("RECT", "Retangular maciça"),
                                                       ("CSOLID", "Circular maciça"),
                                                       ("CTUBE", "Tubo circular"),
                                                       ("I", "Perfil I (duplo T)")])
        s = geo["secao"]
        if s == "RECT":
            geo["sec"] = [perguntar("Base b", 0.05, minimo=0), perguntar("Altura h", 0.10, minimo=0)]
        elif s == "CSOLID":
            geo["sec"] = [perguntar("Raio r", 0.03, minimo=0)]
        elif s == "CTUBE":
            geo["sec"] = [perguntar("Raio interno", 0.045, minimo=0), perguntar("Raio externo", 0.05, minimo=0)]
        else:
            bf, h = perguntar("Largura da mesa bf", 0.10, minimo=0), perguntar("Altura total h", 0.20, minimo=0)
            tf, tw = perguntar("Espessura da mesa tf", 0.0085, minimo=0), perguntar("Espessura da alma tw", 0.0056, minimo=0)
            geo["sec"] = [bf, bf, h, tf, tf, tw]
    elif tipo == "trelica":
        geo["vao"] = perguntar("Vão total", 12.0, minimo=0)
        geo["H"] = perguntar("Altura", 1.5, minimo=0)
        n = perguntar("Número de painéis (par)", 6, int, minimo=1)
        geo["n"] = n + (n % 2)
        geo["A"] = perguntar("Área das barras (m²)", 1.0e-3, minimo=0)
    elif tipo == "solido":
        geo["L"] = perguntar("Comprimento L (X)", 0.2, minimo=0)
        geo["H"] = perguntar("Altura H (Y)", 0.05, minimo=0)
        geo["B"] = perguntar("Largura B (Z)", 0.05, minimo=0)
        geo["d"] = perguntar("Diâmetro de furo passante em Z no centro (0 = sem furo)", 0.0)
    elif tipo == "plano":
        geo["modo"] = escolher("Hipótese 2D:", [("tensao", "Tensão plana (com espessura)"),
                                                ("deformacao", "Deformação plana"),
                                                ("axi", "Axissimétrico (eixo Y)")])
        if geo["modo"] == "axi":
            geo["Ri"] = perguntar("Raio interno", 0.10, minimo=0)
            geo["Re"] = perguntar("Raio externo", 0.15, minimo=0)
            geo["H"] = perguntar("Altura (Y)", 0.30, minimo=0)
        else:
            geo["L"] = perguntar("Comprimento L (X)", 0.4, minimo=0)
            geo["H"] = perguntar("Altura H (Y)", 0.2, minimo=0)
            if geo["modo"] == "tensao":
                geo["t"] = perguntar("Espessura", 0.01, minimo=0)
            geo["d"] = perguntar("Diâmetro de furo central (0 = sem furo)", 0.0)
    return geo


def dim_ref(tipo, geo):
    return {"placa": min(geo.get("a", 1), geo.get("b", 1)),
            "casca_cil": geo.get("R", 1), "viga": geo.get("L", 1),
            "trelica": geo.get("vao", 1), "solido": min(geo.get("L", 1), geo.get("H", 1), geo.get("B", 1)),
            "plano": min(geo.get("H", 1), geo.get("L", geo.get("Re", 1) - geo.get("Ri", 0)))}[tipo]


def q_malha(tipo, geo):
    print("\nMalha:")
    if tipo == "trelica":
        print("  Treliça: 1 elemento LINK180 por barra (automático).")
        return {}
    if tipo == "viga":
        n = perguntar("Número de elementos ao longo da viga (par)", 20, int, minimo=1)
        return {"ndiv": n + (n % 2)}
    if tipo == "casca_cil":
        padrao = 2 * math.pi * geo["R"] / 40
    elif tipo == "solido":
        padrao = dim_ref(tipo, geo) / 8
    else:
        padrao = dim_ref(tipo, geo) / 20
    return {"esize": perguntar("Tamanho do elemento (m)", round(padrao, 5), minimo=0)}


def q_apoio(tipo, geo):
    ops = {
        "placa": [("ssss", "4 bordas simplesmente apoiadas (UZ=0)"),
                  ("cccc", "4 bordas engastadas"),
                  ("cfff", "Engastada em x=0, demais bordas livres")],
        "casca_cil": [("base_eng", "Base engastada, topo livre"),
                      ("base_eng_topo_guia", "Base engastada, topo guiado (UX=UY=0)")],
        "viga": [("biapoiada", "Biapoiada"), ("balanco", "Engastada-livre (balanço)"),
                 ("biengastada", "Biengastada")],
        "trelica": [("isostatica", "Apoio fixo à esquerda e móvel à direita")],
        "solido": [("eng_x0", "Face x=0 engastada")],
        "plano": [("simetria", "UX=0 em x=0 e UY=0 no canto (0,0)"), ("eng_x0", "Borda x=0 engastada")]
                 if geo.get("modo") != "axi" else
                 [("base", "Base y=0 com UY=0, topo livre"), ("base_topo", "Base e topo com UY=0")],
    }[tipo]
    if len(ops) == 1:
        print(f"\nApoio: {ops[0][1]} (automático)")
        return ops[0][0]
    return escolher("Condição de apoio:", ops)


def q_carga(tipo, geo, analise):
    if analise == "modal":
        return None
    flamb = analise in ("flambagem", "flambagem_nl")
    ops = {
        "placa": [("pressao", "Pressão lateral uniforme (Pa)"),
                  ("uniaxial", "Compressão uniaxial na borda x=a (tensão de referência, Pa)"),
                  ("biaxial", "Compressão biaxial nas bordas x=a e y=b (Pa)")],
        "casca_cil": [("axial", "Compressão axial no topo (tensão de referência, Pa)"),
                      ("pressao", "Pressão externa uniforme (Pa)")],
        "viga": [("p_meio", "Força concentrada no meio do vão (N)"),
                 ("p_ponta", "Força concentrada na extremidade x=L (N)"),
                 ("q", "Carga distribuída (N/m)"),
                 ("axial", "Compressão axial na extremidade x=L (N)")],
        "trelica": [("nos_sup", "Força vertical em cada nó do banzo superior (N)")],
        "solido": [("pres_x", "Pressão na face x=L (Pa, + comprime)"),
                   ("pres_topo", "Pressão na face superior y=H (Pa, + para baixo)")],
        "plano": [("tracao", "Tração uniforme na borda x=L (Pa)"),
                  ("pres_topo", "Pressão na borda superior y=H (Pa)")]
                 if geo.get("modo") != "axi" else
                 [("p_int", "Pressão interna (Pa)"), ("p_ext", "Pressão externa (Pa)")],
    }[tipo]
    if flamb:
        excluir = {"placa": {"pressao"}, "viga": {"p_meio", "p_ponta", "q"}}.get(tipo, set())
        ops = [o for o in ops if o[0] not in excluir] or ops
    k = ops[0][0] if len(ops) == 1 else escolher("Carregamento:", ops)
    padroes = {"pressao": 1e4, "uniaxial": 1e6, "biaxial": 1e6, "axial": 1e6 if tipo == "casca_cil" else 1e3,
               "p_meio": 1e3, "p_ponta": 1e3, "q": 1e3, "nos_sup": 1e4, "pres_x": 1e6,
               "pres_topo": 1e6, "tracao": 1e6, "p_int": 1e6, "p_ext": 1e6}
    c = {"tipo": k, "valor": perguntar("Valor", padroes[k])}
    if k == "biaxial":
        c["valor_y"] = perguntar("Valor na direção Y (Pa)", c["valor"])
    if flamb:
        print("  (Na flambagem, esse valor é a carga de REFERÊNCIA: carga crítica = λ × referência.)")
    return c


def q_analise(tipo):
    ops = list(ANALISES.items())
    if tipo == "plano":
        ops = [o for o in ops if o[0] not in ("flambagem", "flambagem_nl")]
    k = escolher("Tipo de análise:", ops)
    a = {"tipo": k}
    if k in ("modal", "flambagem", "flambagem_nl"):
        a["n_modos"] = perguntar("Número de modos", 6 if k == "modal" else 4, int, minimo=0)
    if k in ("nao_linear", "flambagem_nl"):
        a["n_subpassos"] = perguntar("Número inicial de subpassos", 50, int, minimo=0)
    return a


def questionario():
    print("=" * 72)
    print(f" MODELADOR ANSYS (PyMAPDL)  v{__version__}  -  unidades SI")
    print("=" * 72)
    ops = [(k, f"{v[0]}  -> {v[1]}") for k, v in TIPOS.items()]
    ops.insert(0, ("auto", "Não sei - me ajude a escolher"))
    tipo = escolher("Que estrutura/peça você quer modelar?", ops, padrao=2)
    if tipo == "auto":
        tipo = assistente_tipo()
    print(f"\n  >> Tipo: {TIPOS[tipo][0]}  |  Elemento: {TIPOS[tipo][1]}")
    titulo = perguntar("Título do modelo", f"Modelo {tipo}", str)
    analise = q_analise(tipo)
    material = q_material(analise["tipo"] in ("nao_linear", "flambagem_nl"))
    geo = q_geometria(tipo)
    malha = q_malha(tipo, geo)
    apoio = q_apoio(tipo, geo)
    carga = q_carga(tipo, geo, analise["tipo"])
    if analise["tipo"] == "flambagem_nl":
        padrao_imp = {"placa": geo.get("b", 1) / 2000, "casca_cil": geo.get("t", 0.01) / 10}.get(
            tipo, dim_ref(tipo, geo) / 1000)
        analise["imperfeicao"] = perguntar("Amplitude da imperfeição inicial (m)", round(padrao_imp, 8), minimo=0)
        analise["mult_lambda"] = perguntar("Carga aplicada no não linear = k × λ1 × referência; k", 1.5, minimo=0)
    return {"versao": __version__, "titulo": titulo, "tipo": tipo, "elemento": TIPOS[tipo][1],
            "material": material, "geometria": geo, "malha": malha, "apoio": apoio,
            "carga": carga, "analise": analise}


# ---------------------------------------------------------------------------
# Geração do APDL
# ---------------------------------------------------------------------------
def apdl_material_secao(cfg):
    m, geo, tipo = cfg["material"], cfg["geometria"], cfg["tipo"]
    L = [f"MP,EX,1,{g(m['E'])}", f"MP,PRXY,1,{g(m['nu'])}", f"MP,DENS,1,{g(m['rho'])}"]
    if cfg["analise"]["tipo"] in ("nao_linear", "flambagem_nl"):
        L += ["TB,BISO,1,1,2", f"TBDATA,1,{g(m['fy'])},{g(m['Et'])}"]
    if tipo in ("placa", "casca_cil"):
        L += ["ET,1,SHELL181", "KEYOPT,1,3,2      ! integracao completa (flambagem/plasticidade)",
              "SECTYPE,1,SHELL", f"SECDATA,{g(geo['t'])},1,0.0,5   ! 5 pontos na espessura"]
    elif tipo == "viga":
        L += ["ET,1,BEAM188", "KEYOPT,1,3,3      ! funcao de forma cubica",
              f"SECTYPE,1,BEAM,{geo['secao']}", "SECDATA," + ",".join(g(v) for v in geo["sec"])]
    elif tipo == "trelica":
        L += ["ET,1,LINK180", "SECTYPE,1,LINK", f"SECDATA,{g(geo['A'])}"]
    elif tipo == "solido":
        el = "SOLID187" if geo["d"] > 0 else "SOLID186"
        cfg["elemento"] = el
        L += [f"ET,1,{el}"]
    elif tipo == "plano":
        k = {"tensao": 3, "deformacao": 2, "axi": 1}[geo["modo"]]
        L += ["ET,1,PLANE183", f"KEYOPT,1,3,{k}      ! 3=tensao plana c/ esp., 2=def. plana, 1=axissim."]
        if k == 3:
            L += [f"R,1,{g(geo['t'])}"]
    return L


def apdl_geometria_malha(cfg):
    geo, tipo, ms = cfg["geometria"], cfg["tipo"], cfg["malha"]
    L = []
    if tipo == "placa":
        a, b = geo["a"], geo["b"]
        L += [f"RECTNG,0,{g(a)},0,{g(b)}"]
        if geo["furo"] == "circular":
            L += [f"CYL4,{g(geo['xc'])},{g(geo['yc'])},{g(geo['d']/2)}", "ASBA,1,2"]
        elif geo["furo"] == "retangular":
            x1, x2 = geo["xc"] - geo["wf"] / 2, geo["xc"] + geo["wf"] / 2
            y1, y2 = geo["yc"] - geo["hf"] / 2, geo["yc"] + geo["hf"] / 2
            L += [f"RECTNG,{g(x1)},{g(x2)},{g(y1)},{g(y2)}", "ASBA,1,2"]
        L += ["TYPE,1", "MAT,1", "SECNUM,1", f"ESIZE,{g(ms['esize'])}", "MSHAPE,0,2D", "MSHKEY,0", "AMESH,ALL"]
    elif tipo == "casca_cil":
        L += ["K,1,0,0,0", f"K,2,0,0,{g(geo['L'])}", f"CIRCLE,1,{g(geo['R'])},2,,360,4", "L,1,2",
              "ADRAG,1,2,3,4,,,5", "TYPE,1", "MAT,1", "SECNUM,1", f"ESIZE,{g(ms['esize'])}",
              "MSHAPE,0,2D", "MSHKEY,0", "AMESH,ALL"]
    elif tipo == "viga":
        L += ["K,1,0,0,0", f"K,2,{g(geo['L'])},0,0", "K,3,0,1,0         ! orientacao: altura da secao em Y",
              "L,1,2", "LATT,1,,1,,3,,1", f"LESIZE,ALL,,,{ms['ndiv']}", "LMESH,ALL"]
    elif tipo == "trelica":
        n, dx, H = geo["n"], geo["vao"] / geo["n"], geo["H"]
        L += ["TYPE,1", "MAT,1", "SECNUM,1"]
        L += [f"N,{i+1},{g(i*dx)},0,0" for i in range(n + 1)]
        L += [f"N,{100+i},{g(i*dx)},{g(H)},0" for i in range(1, n)]
        el = [(i + 1, i + 2) for i in range(n)]                       # banzo inferior
        el += [(100 + i, 101 + i) for i in range(1, n - 1)]           # banzo superior
        el += [(i + 1, 100 + i) for i in range(1, n)]                 # montantes
        el += [(1, 101), (n + 1, 100 + n - 1)]                        # diagonais extremas
        el += [(100 + i, i + 2) for i in range(1, n // 2)]            # diagonais Pratt (esq.)
        el += [(100 + i, i) for i in range(n // 2 + 1, n)]            # diagonais Pratt (dir.)
        L += [f"E,{i},{j}" for i, j in el]
    elif tipo == "solido":
        Lx, H, B, d = geo["L"], geo["H"], geo["B"], geo["d"]
        L += [f"BLOCK,0,{g(Lx)},0,{g(H)},0,{g(B)}"]
        if d > 0:
            L += [f"WPOFFS,{g(Lx/2)},{g(H/2)},0", f"CYLIND,{g(d/2)},,0,{g(B)}", "WPCSYS,-1,0", "VSBV,1,2"]
        L += ["TYPE,1", "MAT,1", f"ESIZE,{g(ms['esize'])}"]
        L += ["MSHAPE,1,3D", "MSHKEY,0"] if d > 0 else ["MSHAPE,0,3D", "MSHKEY,1"]
        L += ["VMESH,ALL"]
    elif tipo == "plano":
        if geo["modo"] == "axi":
            L += [f"RECTNG,{g(geo['Ri'])},{g(geo['Re'])},0,{g(geo['H'])}"]
        else:
            L += [f"RECTNG,0,{g(geo['L'])},0,{g(geo['H'])}"]
            if geo["d"] > 0:
                L += [f"CYL4,{g(geo['L']/2)},{g(geo['H']/2)},{g(geo['d']/2)}", "ASBA,1,2"]
        L += ["TYPE,1", "MAT,1", "REAL,1", f"ESIZE,{g(ms['esize'])}", "MSHAPE,0,2D", "MSHKEY,0", "AMESH,ALL"]
    return L


def apdl_apoios(cfg):
    geo, tipo, ap = cfg["geometria"], cfg["tipo"], cfg["apoio"]
    c = cfg["carga"] or {}
    L = []
    if tipo == "placa":
        a, b = g(geo["a"]), g(geo["b"])
        bordas = [f"NSEL,S,LOC,X,0", f"NSEL,A,LOC,X,{a}", "NSEL,A,LOC,Y,0", f"NSEL,A,LOC,Y,{b}"]
        if ap == "ssss":
            L += bordas + ["D,ALL,UZ,0"]
            L += ["NSEL,S,LOC,X,0", "D,ALL,UX,0"]
            if c.get("tipo") == "biaxial":
                L += ["NSEL,S,LOC,Y,0", "D,ALL,UY,0"]
            else:
                L += ["NSEL,S,LOC,X,0", "NSEL,R,LOC,Y,0", "D,ALL,UY,0",
                      f"NSEL,S,LOC,X,{a}", "NSEL,R,LOC,Y,0", "D,ALL,UY,0"]
        elif ap == "cccc":
            L += bordas + ["D,ALL,ALL,0"]
        else:
            L += ["NSEL,S,LOC,X,0", "D,ALL,ALL,0"]
    elif tipo == "casca_cil":
        L += ["NSEL,S,LOC,Z,0", "D,ALL,ALL,0"]
        if ap == "base_eng_topo_guia":
            L += [f"NSEL,S,LOC,Z,{g(geo['L'])}", "D,ALL,UX,0,,,,UY"]
    elif tipo == "viga":
        Lx = g(geo["L"])
        axial = c.get("tipo") == "axial"
        if ap == "biapoiada":
            L += ["NSEL,S,LOC,X,0", "D,ALL,UX,0,,,,UY,UZ,ROTX", f"NSEL,S,LOC,X,{Lx}", "D,ALL,UY,0,,,,UZ"]
        elif ap == "balanco":
            L += ["NSEL,S,LOC,X,0", "D,ALL,ALL,0"]
        else:
            L += ["NSEL,S,LOC,X,0", "D,ALL,ALL,0", f"NSEL,S,LOC,X,{Lx}"]
            L += ["D,ALL,UY,0,,,,UZ,ROTX,ROTY,ROTZ"] if axial else ["D,ALL,ALL,0"]
    elif tipo == "trelica":
        L += ["NSEL,ALL", "D,ALL,UZ,0", "D,1,UX,0,,,,UY", f"D,{geo['n']+1},UY,0"]
    elif tipo == "solido":
        L += ["NSEL,S,LOC,X,0", "D,ALL,UX,0,,,,UY,UZ"]
    elif tipo == "plano":
        if geo["modo"] == "axi":
            L += ["NSEL,S,LOC,Y,0", "D,ALL,UY,0"]
            if ap == "base_topo":
                L += [f"NSEL,S,LOC,Y,{g(geo['H'])}", "D,ALL,UY,0"]
        elif ap == "simetria":
            L += ["NSEL,S,LOC,X,0", "D,ALL,UX,0", "NSEL,R,LOC,Y,0", "D,ALL,UY,0"]
        else:
            L += ["NSEL,S,LOC,X,0", "D,ALL,UX,0,,,,UY"]
    return L + ["ALLSEL,ALL"]


def apdl_cargas(cfg):
    """Cargas multiplicadas pelo parâmetro CF (fator de carga)."""
    c = cfg["carga"]
    if not c:
        return []
    geo, tipo, k, v = cfg["geometria"], cfg["tipo"], c["tipo"], c["valor"]
    L = []
    if tipo == "placa":
        a, b, t = geo["a"], geo["b"], geo["t"]
        if k == "pressao":
            L += ["ASEL,ALL", f"SFA,ALL,1,PRES,CF*{g(v)}"]
        else:
            L += [f"NSEL,S,LOC,X,{g(a)}", "*GET,NN,NODE,0,COUNT", f"F,ALL,FX,-CF*{g(v*t*b)}/NN"]
            if k == "biaxial":
                L += [f"NSEL,S,LOC,Y,{g(b)}", "*GET,NN,NODE,0,COUNT", f"F,ALL,FY,-CF*{g(c['valor_y']*t*a)}/NN"]
    elif tipo == "casca_cil":
        if k == "axial":
            P = v * 2 * math.pi * geo["R"] * geo["t"]
            L += [f"NSEL,S,LOC,Z,{g(geo['L'])}", "*GET,NN,NODE,0,COUNT", f"F,ALL,FZ,-CF*{g(P)}/NN"]
        else:
            L += ["ASEL,ALL", f"SFA,ALL,1,PRES,CF*{g(v)}   ! confira o sentido da normal"]
    elif tipo == "viga":
        Lx = geo["L"]
        if k == "p_meio":
            L += [f"NSEL,S,LOC,X,{g(Lx/2)}", f"F,ALL,FY,-CF*{g(v)}"]
        elif k == "p_ponta":
            L += [f"NSEL,S,LOC,X,{g(Lx)}", f"F,ALL,FY,-CF*{g(v)}"]
        elif k == "q":
            L += ["ESEL,ALL", f"SFBEAM,ALL,1,PRES,CF*{g(v)}"]
        else:
            L += [f"NSEL,S,LOC,X,{g(Lx)}", f"F,ALL,FX,-CF*{g(v)}"]
    elif tipo == "trelica":
        L += [f"NSEL,S,LOC,Y,{g(geo['H'])}", f"F,ALL,FY,-CF*{g(v)}"]
    elif tipo == "solido":
        if k == "pres_x":
            L += [f"ASEL,S,LOC,X,{g(geo['L'])}", f"SFA,ALL,,PRES,CF*{g(v)}"]
        else:
            L += [f"ASEL,S,LOC,Y,{g(geo['H'])}", f"SFA,ALL,,PRES,CF*{g(v)}"]
    elif tipo == "plano":
        if k == "tracao":
            L += [f"LSEL,S,LOC,X,{g(geo['L'])}", f"SFL,ALL,PRES,-CF*{g(v)}"]
        elif k == "pres_topo":
            L += [f"LSEL,S,LOC,Y,{g(geo['H'])}", f"SFL,ALL,PRES,CF*{g(v)}"]
        elif k == "p_int":
            L += [f"LSEL,S,LOC,X,{g(geo['Ri'])}", f"SFL,ALL,PRES,CF*{g(v)}"]
        else:
            L += [f"LSEL,S,LOC,X,{g(geo['Re'])}", f"SFL,ALL,PRES,CF*{g(v)}"]
    return L + ["ALLSEL,ALL"]


def apdl_pos_estatico(cfg, nl=False):
    tipo = cfg["tipo"]
    L = ["FINISH", "/POST1", "SET,LAST", "NSORT,U,SUM", "*GET,UMAX,SORT,0,MAX"]
    if tipo == "trelica":
        L += ["ETABLE,SAX,LS,1", "ESORT,ETAB,SAX,0,1", "*GET,SMAXP,SORT,0,MAX"]
    elif tipo == "viga":
        L += ["ETABLE,SDI,SMISC,31", "ETABLE,SBYI,SMISC,32", "ETABLE,SBZI,SMISC,34",
              "ETABLE,SDJ,SMISC,36", "ETABLE,SBYJ,SMISC,37", "ETABLE,SBZJ,SMISC,39",
              "SABS,1", "SADD,SMI,SDI,SBYI,1,1,SBZI,1", "SADD,SMJ,SDJ,SBYJ,1,1,SBZJ,1",
              "SMAX,SMB,SMI,SMJ", "SABS,0", "ESORT,ETAB,SMB,0,1", "*GET,SMAXP,SORT,0,MAX"]
    elif tipo in ("placa", "casca_cil"):
        L += ["SHELL,TOP", "NSORT,S,EQV", "*GET,S_TOP,SORT,0,MAX",
              "SHELL,BOT", "NSORT,S,EQV", "*GET,S_BOT,SORT,0,MAX",
              "SMAXP=MAX(S_TOP,S_BOT)", "SHELL,TOP"]
    else:
        L += ["NSORT,S,EQV", "*GET,SMAXP,SORT,0,MAX"]
    if nl and tipo != "trelica":
        L += ["NSORT,EPPL,EQV", "*GET,EPMAX,SORT,0,MAX"]
    return L


def apdl_pos_curva():
    return ["FINISH", "/POST1", "SET,LAST", "*GET,NSETS,ACTIVE,0,SET,NSET",
            "*DEL,CT,,NOPR", "*DEL,CU,,NOPR",
            "*DIM,CT,ARRAY,NSETS", "*DIM,CU,ARRAY,NSETS",
            "*DO,I,1,NSETS", "SET,,,,,,,I", "*GET,CT(I),ACTIVE,0,SET,TIME",
            "NSORT,U,SUM", "*GET,CU(I),SORT,0,MAX", "*ENDDO",
            "*CFOPEN,curva_carga_desloc,csv", "*VWRITE,CT(1),CU(1)", "(F12.6,',',E16.8)", "*CFCLOS"]


def apdl_pos_autovalores(n):
    return ["FINISH", "/POST1", f"*DIM,FREQS,ARRAY,{n}",
            f"*DO,I,1,{n}", "SET,1,I", "*GET,FREQS(I),ACTIVE,0,SET,FREQ", "*ENDDO"]


def gerar_blocos(cfg):
    """Retorna lista de (nome, linhas, crítico)."""
    a = cfg["analise"]
    t = a["tipo"]
    modelo = (["/FILNAME,modelo,0", f"/TITLE,{ascii_apdl(cfg['titulo'])}", "/PREP7", "*SET,CF,1.0"]
              + apdl_material_secao(cfg) + apdl_geometria_malha(cfg) + apdl_apoios(cfg)
              + apdl_cargas(cfg) + ["FINISH"])
    blocos = [("Modelo (pré-processamento)", modelo, True)]

    def estatico_pstres():
        return ["FINISH", "/SOLU", "ANTYPE,STATIC", "PSTRES,ON", "SOLVE", "FINISH",
                "/SOLU", "ANTYPE,BUCKLE", f"BUCOPT,LANB,{a['n_modos']}", f"MXPAND,{a['n_modos']}",
                "SOLVE", "FINISH"]

    if t == "estatica":
        blocos += [("Solução estática", ["FINISH", "/SOLU", "ANTYPE,STATIC", "SOLVE", "FINISH"], True),
                   ("Pós-processamento", apdl_pos_estatico(cfg), False)]
    elif t == "modal":
        blocos += [("Solução modal", ["FINISH", "/SOLU", "ANTYPE,MODAL", f"MODOPT,LANB,{a['n_modos']}",
                                      f"MXPAND,{a['n_modos']}", "SOLVE", "FINISH"], True),
                   ("Frequências", apdl_pos_autovalores(a["n_modos"]), False)]
    elif t == "flambagem":
        blocos += [("Pré-tensão + flambagem linear", estatico_pstres(), True),
                   ("Fatores de carga crítica", apdl_pos_autovalores(a["n_modos"]), False)]
    elif t == "nao_linear":
        ns = a["n_subpassos"]
        blocos += [("Solução não linear", ["FINISH", "/SOLU", "ANTYPE,STATIC", "NLGEOM,ON",
                                           f"NSUBST,{ns},{ns*10},{max(ns//5, 1)}", "AUTOTS,ON",
                                           "LNSRCH,ON", "OUTRES,ALL,ALL", "NCNV,2", "SOLVE", "FINISH"], False),
                   ("Pós-processamento", apdl_pos_estatico(cfg, nl=True), False),
                   ("Curva carga x deslocamento", apdl_pos_curva(), False)]
    elif t == "flambagem_nl":
        ns = a["n_subpassos"]
        blocos += [("Pré-tensão + flambagem linear", estatico_pstres(), True),
                   ("Fatores de carga crítica", apdl_pos_autovalores(a["n_modos"])
                    + ["SET,1,1", "*GET,LAMB1,ACTIVE,0,SET,FREQ", "FINISH"], True),
                   ("Imperfeição inicial (UPGEOM modo 1)",
                    ["FINISH", "/PREP7", f"UPGEOM,{g(a['imperfeicao'])},1,1,modelo,rst",
                     f"*SET,CF,{g(a['mult_lambda'])}*LAMB1"] + apdl_cargas(cfg) + ["FINISH"], True),
                   ("Solução não linear", ["FINISH", "/SOLU", "ANTYPE,STATIC", "PSTRES,OFF", "NLGEOM,ON",
                                           f"NSUBST,{ns},{ns*20},{max(ns//5, 1)}", "AUTOTS,ON",
                                           "LNSRCH,ON", "OUTRES,ALL,ALL", "NCNV,2", "SOLVE", "FINISH"], False),
                   ("Pós-processamento", apdl_pos_estatico(cfg, nl=True), False),
                   ("Curva carga x deslocamento", apdl_pos_curva(), False)]
    return blocos


def escrever_mac(cfg, blocos, caminho):
    cab = [f"! Gerado por ansys_modelador.py v{__version__} em {datetime.datetime.now():%Y-%m-%d %H:%M}",
           f"! Tipo: {cfg['tipo']}  Elemento: {cfg['elemento']}  Analise: {cfg['analise']['tipo']}",
           "! Unidades SI (m, N, Pa)", "FINISH", "/CLEAR,NOSTART"]
    corpo = []
    for nome, linhas, _ in blocos:
        corpo += ["", f"! ===== {ascii_apdl(nome).upper()} ====="] + linhas
    caminho.write_text("\n".join(cab + corpo) + "\n", encoding="ascii", errors="ignore")


# ---------------------------------------------------------------------------
# Execução no ANSYS
# ---------------------------------------------------------------------------
def ler_param(mapdl, nome):
    try:
        return mapdl.parameters[nome]
    except Exception:
        return None


def executar(cfg, blocos, pasta, exec_file=None):
    try:
        from ansys.mapdl.core import launch_mapdl
    except ImportError:
        print("\n[!] PyMAPDL não instalado. Rode:  pip install -r requirements.txt")
        return None
    print("\nIniciando o ANSYS MAPDL...")
    kw = {"run_location": str(pasta.resolve()), "override": True, "loglevel": "ERROR"}
    if exec_file:
        kw["exec_file"] = exec_file
    mapdl = launch_mapdl(**kw)
    res = {}
    try:
        mapdl.clear()
        for nome, linhas, critico in blocos:
            print(f"  > {nome}...")
            try:
                mapdl.input_strings("\n".join(linhas))
            except Exception as e:
                msg = str(e).splitlines()[0] if str(e) else repr(e)
                print(f"    [!] aviso/erro: {msg[:200]}")
                if critico:
                    raise
        res = coletar(mapdl, cfg)
        graficos(mapdl, cfg, pasta, res)
    finally:
        mapdl.exit()
    return res


def coletar(mapdl, cfg):
    t = cfg["analise"]["tipo"]
    r = {}
    if t in ("estatica", "nao_linear", "flambagem_nl"):
        r["deslocamento_max_m"] = ler_param(mapdl, "UMAX")
        r["tensao_max_Pa"] = ler_param(mapdl, "SMAXP")
        if t != "estatica":
            r["def_plastica_eq_max"] = ler_param(mapdl, "EPMAX")
    if t in ("modal", "flambagem", "flambagem_nl"):
        f = ler_param(mapdl, "FREQS")
        if f is not None:
            chave = "frequencias_Hz" if t == "modal" else "fatores_carga_critica_lambda"
            r[chave] = [float(x) for x in list(f.flatten())]
    if t in ("nao_linear", "flambagem_nl"):
        ct, cu = ler_param(mapdl, "CT"), ler_param(mapdl, "CU")
        cf = ler_param(mapdl, "CF") or 1.0
        if ct is not None:
            ct = [float(x) for x in ct.flatten()]
            r["curva"] = {"fator_carga": [x * cf for x in ct], "desloc_max_m": [float(x) for x in cu.flatten()]}
            r["fator_carga_ultima"] = ct[-1] * cf
            r["fator_carga_aplicado_CF"] = cf
    for k, v in list(r.items()):
        if hasattr(v, "item"):
            r[k] = v.item()
    return r


def graficos(mapdl, cfg, pasta, res):
    try:
        mapdl.post1()
        mapdl.eplot(savefig=str(pasta / "malha.png"), off_screen=True)
    except Exception:
        pass
    t = cfg["analise"]["tipo"]
    try:
        mapdl.post1()
        mapdl.set(1, 1) if t in ("modal", "flambagem") else mapdl.set("LAST")
        nome = {"modal": "modo1.png", "flambagem": "modo_flambagem1.png"}.get(t, "deslocamento.png")
        mapdl.post_processing.plot_nodal_displacement("NORM", savefig=str(pasta / nome), off_screen=True)
    except Exception:
        pass
    if "curva" in res:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(6, 4))
            ax.plot(res["curva"]["desloc_max_m"], res["curva"]["fator_carga"], "o-", ms=3)
            ax.set_xlabel("Deslocamento máximo (m)")
            ax.set_ylabel("Fator de carga (× referência)")
            ax.set_title(cfg["titulo"])
            ax.grid(alpha=0.3)
            fig.tight_layout()
            fig.savefig(pasta / "curva_carga_desloc.png", dpi=150)
        except Exception:
            pass


def imprimir_resultados(cfg, res, pasta):
    if not res:
        return
    c = cfg["carga"]
    print("\n" + "=" * 72 + "\n RESULTADOS\n" + "=" * 72)
    for k, v in res.items():
        if k == "curva":
            continue
        if isinstance(v, list):
            for i, x in enumerate(v, 1):
                extra = f"   -> carga crítica = {x*c['valor']:.6g}" if c and "lambda" in k else ""
                print(f"  {k} [{i}]: {x:.6g}{extra}")
        elif v is not None:
            print(f"  {k}: {v:.6g}")
    if c and "fator_carga_ultima" in res:
        print(f"  carga última ≈ {res['fator_carga_ultima']*c['valor']:.6g} (unid. da carga de referência)")
    (pasta / "resultados.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nArquivos em: {pasta.resolve()}")


# ---------------------------------------------------------------------------
def resumo(cfg):
    a = cfg["analise"]
    print("\n" + "-" * 72)
    print(f" Modelo   : {cfg['titulo']}")
    print(f" Tipo     : {TIPOS[cfg['tipo']][0]}")
    print(f" Elemento : {cfg['elemento']}")
    print(f" Material : {cfg['material']['nome']}")
    print(f" Análise  : {ANALISES[a['tipo']]}")
    print(f" Apoio    : {cfg['apoio']}")
    print(f" Carga    : {cfg['carga']}")
    print("-" * 72)


def main():
    ap = argparse.ArgumentParser(description="Modelador interativo de estruturas no ANSYS MAPDL (PyMAPDL).")
    ap.add_argument("--config", help="arquivo .json com respostas salvas")
    ap.add_argument("--somente-apdl", action="store_true", help="só gera o .mac, não executa o ANSYS")
    ap.add_argument("--exec-file", help="caminho do executável do ANSYS (se não for detectado)")
    ap.add_argument("--pasta", help="pasta de saída")
    args = ap.parse_args()

    try:
        if args.config:
            cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
        else:
            cfg = questionario()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelado.")
        sys.exit(1)

    blocos = gerar_blocos(cfg)
    resumo(cfg)
    slug = ascii_apdl(cfg["titulo"]).strip().replace(" ", "_") or "modelo"
    pasta = Path(args.pasta or f"resultados/{slug}_{datetime.datetime.now():%Y%m%d_%H%M%S}")
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    escrever_mac(cfg, blocos, pasta / "modelo.mac")
    print(f"\nAPDL gerado : {pasta / 'modelo.mac'}")
    print(f"Respostas   : {pasta / 'config.json'}  (reuse com --config)")

    if args.somente_apdl:
        return
    if not args.config and not sim_nao("Executar agora no ANSYS?", "s"):
        return
    res = executar(cfg, blocos, pasta, args.exec_file)
    imprimir_resultados(cfg, res, pasta)


if __name__ == "__main__":
    main()
