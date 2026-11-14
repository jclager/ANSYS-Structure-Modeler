# ANSYS Structure Modeler

🇺🇸 [English version](README.md)

**Modele estruturas no ANSYS respondendo perguntas, sem escrever uma linha de APDL.**

> Montar um modelo no ANSYS Mechanical APDL exige decidir dezenas de detalhes: qual elemento usar, quais KEYOPTs, como definir a seção, a malha, os apoios, as cargas e o tipo de análise. Este projeto reúne essas decisões em um questionário: você descreve a peça e o programa configura o resto, gera um arquivo APDL reproduzível e, se o ANSYS estiver instalado, executa a análise e entrega os resultados.

Aqui você encontra:

- **O questionário:** perguntas guiadas sobre a peça, o material, a geometria, os apoios, as cargas e a análise, com valores sugeridos em cada pergunta.
- **A configuração automática:** a escolha do elemento finito, das KEYOPTs, da seção, da malha e dos comandos de solução adequados a cada tipo de estrutura.
- **A execução e o pós-processamento:** solução no ANSYS via PyMAPDL, com deslocamentos, tensões, frequências, fatores de flambagem, curva carga × deslocamento e figuras.

---

## Sumário

1. [Como funciona em uma página](#1-como-funciona-em-uma-página)
2. [Estruturas e configurações automáticas](#2-estruturas-e-configurações-automáticas)
3. [Análises disponíveis](#3-análises-disponíveis)
4. [Passo a passo](#4-passo-a-passo)
5. [Opções de linha de comando](#5-opções-de-linha-de-comando)
6. [Resultados gerados](#6-resultados-gerados)
7. [Exemplos prontos](#7-exemplos-prontos)
8. [Cuidados e limitações](#8-cuidados-e-limitações)
9. [Problemas comuns](#9-problemas-comuns)
10. [Mapa do repositório](#10-mapa-do-repositório)
11. [Melhorias futuras](#11-melhorias-futuras)
12. [Contribuindo e licença](#12-contribuindo-e-licença)

---

## 1. Como funciona em uma página

```
 Questionário            Configuração automática          Saídas
 ─────────────           ───────────────────────          ──────
 Tipo de peça    ──►     Elemento + KEYOPTs        ──►    modelo.mac  (APDL completo)
 Análise                 Material (+ curva BISO)          config.json (respostas)
 Material                Geometria + malha
 Geometria               Apoios + cargas           ──►    ANSYS (PyMAPDL)
 Malha                   Comandos de solução                    │
 Apoio e carga                                                  ▼
                                                          resultados.json + figuras
```

Unidades: **SI** (m, N, Pa, kg/m³).

## 2. Estruturas e configurações automáticas

| Estrutura | Elemento | Configuração adotada |
|---|---|---|
| Placa / chapa plana (furo circular ou retangular opcional) | SHELL181 | KEYOPT(3)=2 (integração completa), 5 pontos de integração na espessura, malha livre de quadriláteros |
| Casca cilíndrica (tubo de parede fina, tanque, torre) | SHELL181 | Geometria por ADRAG, base engastada |
| Viga / coluna / eixo (retangular, circular, tubo, perfil I) | BEAM188 | KEYOPT(3)=3 (função de forma cúbica), orientação por keypoint |
| Treliça plana Pratt | LINK180 | Um elemento por barra, UZ=0 |
| Bloco 3D (furo passante opcional) | SOLID186 / SOLID187 | Hexaedros mapeados / tetraedros quando há furo |
| Seção 2D | PLANE183 | Tensão plana, deformação plana ou axissimétrico |

**Não sabe qual escolher?** A opção *"Não sei – me ajude a escolher"* classifica a peça pelas três dimensões principais:

| Proporção | Classificação |
|---|---|
| Uma dimensão ≥ 10 × as outras | Viga ou treliça |
| Espessura ≤ 1/10 das outras | Placa ou casca |
| Robusta nas três direções | Sólido 3D ou seção 2D |

Todas as dimensões de cada forma são perguntadas, com valores sugeridos. Apoios e cargas são escolhidos entre opções pré-definidas para cada estrutura.

## 3. Análises disponíveis

| Análise | Comandos principais | Resultado |
|---|---|---|
| Estática linear | `ANTYPE,STATIC` | Deslocamento e tensão de von Mises máximos |
| Modal | `MODOPT,LANB` | Frequências naturais |
| Flambagem linear | `PSTRES,ON` → `ANTYPE,BUCKLE` | Fatores de carga crítica λ |
| Não linear | `TB,BISO` + `NLGEOM,ON` | Curva carga × deslocamento, deformação plástica |
| Flambagem elasto-plástica | autovalor → `UPGEOM` (imperfeição pelo modo 1) → não linear com carga k·λ1 | Carga última e curva carga × deslocamento |

## 4. Passo a passo

### Passo 1: instalar

Requisitos: Python 3.9 ou superior e, para executar as análises, ANSYS Mechanical APDL com licença válida.

```bash
git clone https://github.com/jclager/ANSYS-Structure-Modeler.git
cd ANSYS-Structure-Modeler
pip install -r requirements.txt
```

### Passo 2: executar e responder ao questionário

```bash
python ansys_modelador.py
```

Trecho real do questionário:

```
Que estrutura/peça você quer modelar?
   1 - Não sei - me ajude a escolher
   2 - Placa / chapa plana (com ou sem furo)  -> SHELL181
   3 - Casca cilíndrica (tubo de parede fina, tanque, torre)  -> SHELL181
   4 - Viga / coluna / eixo (barra esbelta)  -> BEAM188
   5 - Treliça plana (barras articuladas, tipo Pratt)  -> LINK180
   6 - Bloco / peça maciça 3D (com ou sem furo passante)  -> SOLID186
   7 - Seção 2D: tensão plana, deformação plana ou axissimétrico  -> PLANE183
  Opção [2]:
```

Pressione **Enter** para aceitar o valor sugerido entre colchetes.

### Passo 3: conferir o resumo

Antes de executar, o programa mostra o resumo do modelo (tipo, elemento, material, análise, apoio e carga) e grava `modelo.mac` e `config.json`.

### Passo 4: executar no ANSYS

Responda **s** em *"Executar agora no ANSYS?"*. O PyMAPDL abre o ANSYS, roda o modelo bloco a bloco, pós-processa e fecha.

Sem ANSYS? Use o `modelo.mac` gerado: abra no ANSYS Mechanical APDL e rode com **File → Read Input from**, ou com `/INPUT,modelo,mac`.

### Passo 5: ler os resultados

Os resultados aparecem na tela e ficam salvos em `resultados/<modelo>_<data>/`.

### Passo 6: repetir ou variar o modelo

Edite o `config.json` (por exemplo, a espessura ou o diâmetro do furo) e rode de novo sem passar pelo questionário:

```bash
python ansys_modelador.py --config resultados/<modelo>_<data>/config.json
```

## 5. Opções de linha de comando

| Opção | Função |
|---|---|
| *(sem opção)* | Questionário interativo |
| `--config arquivo.json` | Reutiliza respostas salvas, sem perguntas |
| `--somente-apdl` | Só gera o `.mac`, não executa o ANSYS |
| `--exec-file caminho` | Caminho do executável do ANSYS, se não for detectado sozinho |
| `--pasta caminho` | Pasta de saída personalizada |

Exemplo com o executável no Windows:

```bash
python ansys_modelador.py --exec-file "C:/Program Files/ANSYS Inc/v242/ansys/bin/winx64/ANSYS242.exe"
```

## 6. Resultados gerados

| Arquivo | Conteúdo |
|---|---|
| `modelo.mac` | APDL completo, roda direto no ANSYS |
| `config.json` | Respostas do questionário |
| `resultados.json` | Deslocamento e tensão máximos, frequências, fatores λ, carga última |
| `malha.png` | Malha |
| `deslocamento.png` / `modo1.png` / `modo_flambagem1.png` | Deformada ou modo |
| `curva_carga_desloc.csv` / `.png` | Curva das análises não lineares |

## 7. Exemplos prontos

| Arquivo | Caso |
|---|---|
| `exemplos/placa_furada_flambagem_elastoplastica.json` | Placa de aço 1,0 × 0,5 × 0,01 m com furo circular central, 4 bordas apoiadas, compressão uniaxial, flambagem elasto-plástica |
| `exemplos/casca_cilindrica_flambagem.json` | Casca cilíndrica sob compressão axial, flambagem linear |

```bash
python ansys_modelador.py --config exemplos/placa_furada_flambagem_elastoplastica.json
```

## 8. Cuidados e limitações

- Na flambagem, a carga informada é uma carga de **referência**: carga crítica = λ × referência.
- Na flambagem elasto-plástica, a carga última é a do último subpasso convergido (controle por carga).
- Cargas de borda em placas e cascas são distribuídas igualmente entre os nós da borda.
- Pressão em casca cilíndrica: confira o sentido da normal das áreas.
- A tensão máxima em vigas (BEAM188) é estimada pela soma das tensões axial e de flexão nas fibras extremas.
- Valide os primeiros modelos com soluções analíticas conhecidas (por exemplo, viga biapoiada, placa de Timoshenko) antes de usar em trabalho final.

## 9. Problemas comuns

| Problema | Solução |
|---|---|
| `PyMAPDL não instalado` | Rode `pip install -r requirements.txt` |
| ANSYS não encontrado | Informe o executável com `--exec-file` |
| Erro de licença | Verifique o servidor de licenças do ANSYS |
| Análise não linear para antes do fim | Normal após o colapso: a carga última é a do último subpasso convergido. Aumente os subpassos se parar cedo demais |
| Figuras não geradas | Os gráficos dependem do PyVista (instalado com o PyMAPDL); os resultados numéricos continuam em `resultados.json` |

## 10. Mapa do repositório

```
ANSYS-Structure-Modeler/
├── ansys_modelador.py      # programa principal
├── exemplos/               # configurações prontas (.json)
├── requirements.txt        # dependências Python
├── README.md               # documentação em inglês
├── README.pt-BR.md         # documentação em português
├── LICENSE                 # licença MIT
└── .gitignore
```

## 11. Melhorias futuras

**Formas adicionais**

| Estrutura | A incluir |
|---|---|
| Viga | Perfil H, seções quadrada e retangular ocas, seções cônicas (maciças ou ocas), perfis U/C, L e T |
| Sólido | Esfera, cilindro, cone, tubo de parede grossa, anel, peças combinadas |
| Placa | Placa circular, vários furos, outros formatos de furo |
| Casca | Cone, esfera, calota esférica |
| Treliça | Warren, Howe e treliças espaciais |

**Apoios e cargas**

- Perguntar onde fixar a estrutura (face, borda ou ponto) e quais eixos travar (deslocamentos e rotações).
- Perguntar onde aplicar cada carga e em qual direção.

**Interface**

- Versão do questionário em inglês.

Ao longo do desenvolvimento do projeto, poderão surgir outras melhorias.

## 12. Contribuindo e licença

Sugestões e correções são bem-vindas: abra uma *issue* ou envie um *pull request*.

Distribuído sob a licença **MIT**. Veja [LICENSE](LICENSE).

**Autor:** José Cristiano Lager
