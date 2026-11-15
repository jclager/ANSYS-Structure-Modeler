# ANSYS Structure Modeler

🇧🇷 [Versão em português](README.pt-BR.md)

**Model structures in ANSYS by answering questions, without writing a single line of APDL.**

> Building a model in ANSYS Mechanical APDL requires dozens of decisions: which element to use, which KEYOPTs, how to define the cross-section, the mesh, the supports, the loads and the analysis type. This project gathers those decisions into a questionnaire: you describe the part and the program configures the rest, generates a reproducible APDL file and, if ANSYS is installed, runs the analysis and delivers the results.

What you will find here:

- **The questionnaire:** guided questions about the part, material, geometry, supports, loads and analysis, with suggested values for every question.
- **The automatic setup:** selection of the finite element, KEYOPTs, cross-section, mesh and solution commands suited to each structure type.
- **Execution and post-processing:** solution in ANSYS through PyMAPDL, with displacements, stresses, frequencies, buckling factors, load × displacement curve and figures.

> The program's prompts are currently in Portuguese (an English interface is planned).

---

## Table of contents

1. [How it works on one page](#1-how-it-works-on-one-page)
2. [Structures and automatic settings](#2-structures-and-automatic-settings)
3. [Available analyses](#3-available-analyses)
4. [Step by step](#4-step-by-step)
5. [Command-line options](#5-command-line-options)
6. [Generated results](#6-generated-results)
7. [Ready-made examples](#7-ready-made-examples)
8. [Cautions and limitations](#8-cautions-and-limitations)
9. [Common problems](#9-common-problems)
10. [Repository map](#10-repository-map)
11. [Future improvements](#11-future-improvements)
12. [Contributing and license](#12-contributing-and-license)

---

## 1. How it works on one page

```
 Questionnaire           Automatic setup                  Outputs
 ─────────────           ───────────────                  ───────
 Part type       ──►     Element + KEYOPTs         ──►    modelo.mac  (complete APDL)
 Analysis                Material (+ BISO curve)          config.json (answers)
 Material                Geometry + mesh
 Geometry                Supports + loads          ──►    ANSYS (PyMAPDL)
 Mesh                    Solution commands                      │
 Support and load                                               ▼
                                                          resultados.json + figures
```

Units: **SI** (m, N, Pa, kg/m³).

## 2. Structures and automatic settings

| Structure | Element | Adopted settings |
|---|---|---|
| Flat plate (optional circular or rectangular hole) | SHELL181 | KEYOPT(3)=2 (full integration), 5 integration points through thickness, free quad mesh |
| Cylindrical shell (thin-walled tube, tank, tower) | SHELL181 | Geometry by ADRAG, clamped base |
| Beam / column / shaft (rectangular, circular, tube, I-section) | BEAM188 | KEYOPT(3)=3 (cubic shape function), orientation keypoint |
| Planar Pratt truss | LINK180 | One element per member, UZ=0 |
| 3D block (optional through hole) | SOLID186 / SOLID187 | Mapped hexahedra / tetrahedra when there is a hole |
| 2D section | PLANE183 | Plane stress, plane strain or axisymmetric |

**Not sure which one to choose?** The *"I don't know – help me choose"* option classifies the part from its three main dimensions:

| Proportion | Classification |
|---|---|
| One dimension ≥ 10 × the others | Beam or truss |
| Thickness ≤ 1/10 of the others | Plate or shell |
| Bulky in all three directions | 3D solid or 2D section |

All dimensions of each shape are requested, with suggested values. Supports and loads are chosen from predefined options for each structure.

## 3. Available analyses

| Analysis | Main commands | Result |
|---|---|---|
| Linear static | `ANTYPE,STATIC` | Maximum displacement and von Mises stress |
| Modal | `MODOPT,LANB` | Natural frequencies |
| Linear buckling | `PSTRES,ON` → `ANTYPE,BUCKLE` | Critical load factors λ |
| Nonlinear | `TB,BISO` + `NLGEOM,ON` | Load × displacement curve, plastic strain |
| Elasto-plastic buckling | eigenvalue → `UPGEOM` (mode 1 imperfection) → nonlinear with load k·λ1 | Ultimate load and load × displacement curve |

## 4. Step by step

### Step 1: install

Requirements: Python 3.9 or later and, to run the analyses, ANSYS Mechanical APDL with a valid license.

```bash
git clone https://github.com/jclager/ANSYS-Structure-Modeler.git
cd ANSYS-Structure-Modeler
pip install -r requirements.txt
```

### Step 2: run and answer the questionnaire

```bash
python ansys_modelador.py
```

Real excerpt of the questionnaire (in Portuguese):

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

Press **Enter** to accept the suggested value in brackets.

### Step 3: check the summary

Before running, the program shows the model summary (type, element, material, analysis, support and load) and saves `modelo.mac` and `config.json`.

### Step 4: run in ANSYS

Answer **s** (yes) to *"Executar agora no ANSYS?"* (Run now in ANSYS?). PyMAPDL starts ANSYS, runs the model block by block, post-processes and closes it.

No ANSYS? Use the generated `modelo.mac`: open ANSYS Mechanical APDL and run it with **File → Read Input from**, or with `/INPUT,modelo,mac`.

### Step 5: read the results

Results are printed on screen and saved in `resultados/<model>_<date>/`.

### Step 6: repeat or vary the model

Edit `config.json` (for example, the thickness or the hole diameter) and run again without the questionnaire:

```bash
python ansys_modelador.py --config resultados/<model>_<date>/config.json
```

## 5. Command-line options

| Option | Function |
|---|---|
| *(no option)* | Interactive questionnaire |
| `--config file.json` | Reuses saved answers, no questions |
| `--somente-apdl` | Only generates the `.mac`, does not run ANSYS |
| `--exec-file path` | Path to the ANSYS executable, if not detected automatically |
| `--pasta path` | Custom output folder |

Example with the executable on Windows:

```bash
python ansys_modelador.py --exec-file "C:/Program Files/ANSYS Inc/v242/ansys/bin/winx64/ANSYS242.exe"
```

## 6. Generated results

| File | Content |
|---|---|
| `modelo.mac` | Complete APDL input, runs directly in ANSYS |
| `modelo.db` | ANSYS database: open with **File → Resume from** to see the model |
| `modelo.rst` | ANSYS results file |
| `config.json` | Questionnaire answers |
| `resultados.json` | Maximum displacement and stress, frequencies, λ factors, ultimate load |
| `malha.png` | Mesh |
| `deslocamento.png` / `modo1.png` / `modo_flambagem1.png` | Deformed shape or mode |
| `curva_carga_desloc.csv` / `.png` | Curve of nonlinear analyses |

## 7. Ready-made examples

| File | Case |
|---|---|
| `exemplos/placa_furada_flambagem_elastoplastica.json` | 1.0 × 0.5 × 0.01 m steel plate with central circular hole, 4 simply supported edges, uniaxial compression, elasto-plastic buckling |
| `exemplos/casca_cilindrica_flambagem.json` | Cylindrical shell under axial compression, linear buckling |

```bash
python ansys_modelador.py --config exemplos/placa_furada_flambagem_elastoplastica.json
```

## 8. Cautions and limitations

- In buckling analyses the given load is a **reference** load: critical load = λ × reference.
- In elasto-plastic buckling, the ultimate load is that of the last converged substep (load control).
- Edge loads on plates and shells are distributed equally among the edge nodes.
- Pressure on the cylindrical shell: check the direction of the area normals.
- Truss (LINK180): one element per member and no bending stiffness, so the modal analysis shows only the global modes of the truss, not the lateral vibration of each member.
- The maximum stress in beams (BEAM188) is estimated by adding axial and bending stresses at the extreme fibers.
- Validate your first models against known analytical solutions (for example, a simply supported beam or a Timoshenko plate) before using them in final work.

## 9. Common problems

| Problem | Solution |
|---|---|
| `PyMAPDL não instalado` (PyMAPDL not installed) | Run `pip install -r requirements.txt` |
| ANSYS not found | Provide the executable with `--exec-file` |
| License error | Check the ANSYS license server |
| Nonlinear analysis stops before the end | Expected after collapse: the ultimate load is that of the last converged substep. Increase the substeps if it stops too early |
| Figures not generated | Install PyVista with `pip install pyvista`; the reason is shown on screen and numerical results remain in `resultados.json` |

## 10. Repository map

```
ANSYS-Structure-Modeler/
├── ansys_modelador.py      # main program
├── exemplos/               # ready-made configurations (.json)
├── requirements.txt        # Python dependencies
├── README.md               # documentation in English
├── README.pt-BR.md         # documentation in Portuguese
├── LICENSE                 # MIT license
└── .gitignore
```

## 11. Future improvements

**Additional shapes**

| Structure | To be added |
|---|---|
| Beam | H-section, square and rectangular hollow sections, tapered (conical) sections – solid or hollow, U/C, L and T sections |
| Solid | Sphere, cylinder, cone, thick-walled tube, ring, combined parts |
| Plate | Circular plate, multiple holes, other hole shapes |
| Shell | Cone, sphere, spherical cap |
| Truss | Warren, Howe and space trusses |

**Supports and loads**

- Ask where to fix the structure (face, edge or point) and which axes to restrain (displacements and rotations).
- Ask where to apply each load and in which direction.

**Interface**

- English version of the questionnaire.

Further improvements may arise throughout the development of the project.

## 12. Contributing and license

Suggestions and fixes are welcome: open an *issue* or submit a *pull request*.

Distributed under the **MIT** license. See [LICENSE](LICENSE).

**Author:** José Cristiano Lager
