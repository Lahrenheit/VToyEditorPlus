# <img src="https://raw.githubusercontent.com/Lahrenheit/VToyEditorPlus/refs/heads/master/vtoy.png" width="50" height="50"/> VToyEditor Plus+

**English** · [Español](#español) · [Português](#português)

Map and scene editor for **Torrente Online** (Virtual Toys engine). It is based on Patoke's VToyEditor and made by **Lahrenheit**.

📘 **User manual (PDF)** — [English](docs/Manual_VToyEditorPlus_en.pdf) · [Español](docs/Manual_VToyEditorPlus_es.pdf) · [Português](docs/Manual_VToyEditorPlus_pt.pdf). Each one has a clickable index and covers every function, plus step-by-step map creation. Also in the editor: *Help → User manual (PDF)*.
🗒️ **Technical history of every change (Spanish):** [docs/CHANGELOG.md](docs/CHANGELOG.md)
⬇️ **Downloads / new versions:** https://github.com/Lahrenheit/VToyEditorPlus/releases

---

## English

### What it does
- **Opens and saves every file of the game**, byte for byte: `demo.vpk`, scenes `.scn`, maps `.opt`, floor collision `.hm`, models `.nfo`, animations `.key`, textures `.tex`.
- **Draws the map in 3D** and lets you edit everything in it:
  - modules (start points, health packs, flags, bombs, cars, doors…), props, meshes, lights, decals, fog, sky, music;
  - every edit can be undone (Ctrl+Z).
- **Creates new maps** three ways:
  - **from zero**: floor and walls, in any game mode;
  - **from Counter-Strike 1.6**: `.bsp` / `.rmf`, with their textures (`.wad`), collision, start points, bomb sites and the CS light;
  - **from Torrente, el juego**: models, maps and whole scenes, converted to Online.
- **Supports all 4 game modes**:
  - Deathmatch (DM), Team Deathmatch (DMT), Capture the Flag (B) and Destroy the Target (DO, with sites A and B);
  - DO options: bomb time, HUD, radar;
  - weapons per map, health-pack respawn and weather (rain / storm).
- **Building tools**:
  - shapes and solids with collision, paths, object brush, measuring;
  - collision editing, painting faces, importing OBJ, reusable pieces.
- **Checks before you play**:
  - the map check, a walk test with the real collision, a fall / trap finder;
  - start-point checks, team balance, a match simulation, a load map.
- **Sharing your maps**: export a map as `.zip` and install a `.zip` without ever overwriting game files. Your saves are kept in a 10-step history.
- **Interface languages**: English, Spanish and Portuguese. The editor can **check GitHub for new versions** and update itself.

### Install and run
1. Download the latest release and unzip the **whole folder**, for example into `E:\Juegos\Torrente On-Line\tools\VToyEditor`.
2. Run `VToyEditor.exe`.
3. The first time, pick the game's `demo.vpk` (or a folder already unpacked). It is unpacked once into `<name>_unpacked`.
4. Choose the language in **Language**.
5. Your settings are kept in `vtoy_editor.json`, next to the `.exe`.

From source (Python 3.10–3.13): `pip install -r requirements.txt`, then `python run_editor.py`. To build the `.exe`: `build_exe.bat`.

### Quick start
| I want to… | Where |
|---|---|
| Open a map | *DEBUG → Scene list* → **Load Scene** |
| Fly / look | **Alt** = free flight (WASD, mouse); in edit mode **hold right click** to look |
| Select / move / rotate | tools **1–4** (Select, Move, Rotate, Scale), or **G** / **R** / **T** + mouse |
| A new map from zero | *Map tools → Build → New map from zero* |
| A new map from CS 1.6 | *File → New map from CS 1.6 (.bsp / .rmf)…* |
| Use Torrente, el juego | *File → Torrente, el juego folder…*, then *DEBUG → Library* |
| Check the map | *Map tools → Check → Map check* (it also runs on every save) |
| Try it in the game | *File → Save, pack and play in the game* |
| Share it | *File → Export this map as .zip* / *Install map from zip…* |

### Main shortcuts
| Key | Action |
|---|---|
| Alt | free flight on / off (Esc goes back to edit mode) |
| W A S D, Shift | move, faster |
| Space / E, Ctrl / C | up, down (free flight) |
| 1 … 9 | tools: Select, Move, Rotate, Scale, Pen, Fill, Measure, Collision, Paint faces |
| G / R / T + mouse | move / rotate / scale the selection (wheel: height / roll) |
| Q | copy the selection (the copy follows the mouse) |
| Del | delete the selection |
| H / Shift+H | hide the selection / show everything |
| Ctrl+Z / Ctrl+Y | undo / redo |
| Ctrl+P | command search (and your own shortcuts) |
| F1 | info panel on / off |
| F11 / F12 | full screen / screenshot |

### Good to know
- **Nothing of the game is overwritten.** Imported files that clash get a new name, and installing a map skips files the game already has.
- **Copy the mode DLLs too.** Maps in DO mode, or with weapons / weather of their own, need their mode DLL. It comes in the map's `.zip` and must be copied into the game folder on the server **and** on every player's PC.
- **Low FPS?** Run the editor on the dedicated graphics card (Windows → Graphics settings).
- **Problems?** Look in `vtoy_editor.log`, next to the `.exe`.

---

## Español

### Qué hace
- **Abre y guarda todos los archivos del juego**, byte a byte: `demo.vpk`, escenas `.scn`, mapas `.opt`, colisión del piso `.hm`, modelos `.nfo`, animaciones `.key`, texturas `.tex`.
- **Muestra el mapa en 3D** y deja editar todo lo que tiene:
  - módulos (puntos de inicio, botiquines, banderas, bombas, autos, puertas…), props, mallas, luces, decals, niebla, cielo, música;
  - todo cambio se deshace con Ctrl+Z.
- **Crea mapas nuevos** de tres formas:
  - **desde cero**: suelo y paredes, en cualquier modo de juego;
  - **desde Counter-Strike 1.6**: `.bsp` / `.rmf`, con sus texturas (`.wad`), colisión, puntos de inicio, sitios de bomba y la luz de CS;
  - **desde Torrente, el juego**: modelos, mapas y escenas enteras, convertidos a Online.
- **Trae los 4 modos de juego**:
  - Deathmatch (DM), Deathmatch por equipos (DMT), Capturar la bandera (B) y Destruir el objetivo (DO, con sitios A y B);
  - opciones de DO: tiempo de la bomba, HUD, radar;
  - armas por mapa, tiempo de reaparición de botiquines y clima (lluvia / tormenta).
- **Herramientas para construir**:
  - formas y sólidos con colisión, recorridos, pincel de objetos, medir;
  - editar colisión, pintar caras, importar OBJ, piezas reutilizables.
- **Revisiones antes de jugar**:
  - revisar mapa, prueba de recorrido con la colisión real, buscador de caídas y trampas;
  - revisión de puntos de aparición, balance de equipos, simulación de partida, mapa de carga.
- **Compartir mapas**: exporta un mapa en `.zip` e instala un `.zip` sin pisar nunca archivos del juego. Tus guardados quedan en un historial de 10 pasos.
- **Idiomas de la interfaz**: inglés, español y portugués. El editor puede **buscar versiones nuevas en GitHub** y actualizarse solo.

### Instalar y abrir
1. Bajá el último release y descomprimí la **carpeta entera**, por ejemplo en `E:\Juegos\Torrente On-Line\tools\VToyEditor`.
2. Abrí `VToyEditor.exe`.
3. La primera vez, elegí el `demo.vpk` del juego (o una carpeta ya desempaquetada). Se desempaqueta una sola vez en `<nombre>_unpacked`.
4. Elegí el idioma en **Idioma**.
5. Tus opciones quedan en `vtoy_editor.json`, al lado del `.exe`.

Desde el código (Python 3.10–3.13): `pip install -r requirements.txt` y después `python run_editor.py`. Para armar el `.exe`: `build_exe.bat`.

### Primeros pasos
| Quiero… | Dónde |
|---|---|
| Abrir un mapa | *DEBUG → Lista de escenas* → **Cargar escena** |
| Volar / mirar | **Alt** = vuelo libre (WASD, mouse); en modo edición, **mantener clic derecho** para mirar |
| Seleccionar / mover / girar | herramientas **1–4** (Seleccionar, Mover, Rotar, Escalar), o **G** / **R** / **T** + mouse |
| Un mapa nuevo desde cero | *Herramientas del mapa → Construir → Mapa nuevo desde cero* |
| Un mapa nuevo desde CS 1.6 | *Archivo → Mapa nuevo desde CS 1.6 (.bsp / .rmf)…* |
| Usar Torrente, el juego | *Archivo → Carpeta de Torrente, el juego…*, después *DEBUG → Library* |
| Revisar el mapa | *Herramientas del mapa → Revisar → Revisar mapa* (también se hace sola en cada guardado) |
| Probarlo en el juego | *Archivo → Guardar, empaquetar y probar en el juego* |
| Compartirlo | *Archivo → Exportar este mapa como .zip* / *Instalar mapa desde zip…* |

### Atajos principales
| Tecla | Acción |
|---|---|
| Alt | vuelo libre sí / no (Esc vuelve al modo edición) |
| W A S D, Shift | moverse, más rápido |
| Espacio / E, Ctrl / C | subir, bajar (vuelo libre) |
| 1 … 9 | herramientas: Seleccionar, Mover, Rotar, Escalar, Pluma, Relleno, Medir, Colisión, Pintar caras |
| G / R / T + mouse | mover / girar / escalar lo seleccionado (rueda: altura / alabeo) |
| Q | copiar lo seleccionado (la copia sigue al mouse) |
| Supr | borrar lo seleccionado |
| H / Shift+H | ocultar lo seleccionado / mostrar todo |
| Ctrl+Z / Ctrl+Y | deshacer / rehacer |
| Ctrl+P | buscador de comandos (y tus propios atajos) |
| F1 | panel de información sí / no |
| F11 / F12 | pantalla completa / captura |

### Para tener en cuenta
- **Nunca se pisa nada del juego.** Lo importado que choca de nombre entra con otro nombre, e instalar un mapa saltea los archivos que el juego ya tiene.
- **Copiá también las DLL del modo.** Los mapas DO, o con armas / clima propios, usan su DLL del modo. Viene en el `.zip` del mapa y va en la carpeta del juego del servidor **y** de cada jugador.
- **¿Pocos FPS?** Hacé que el editor use la placa de video dedicada (Windows → Configuración de gráficos).
- **¿Problemas?** Mirá `vtoy_editor.log`, al lado del `.exe`.

---

## Português

### O que faz
- **Abre e salva todos os arquivos do jogo**, byte a byte: `demo.vpk`, cenas `.scn`, mapas `.opt`, colisão do piso `.hm`, modelos `.nfo`, animações `.key`, texturas `.tex`.
- **Mostra o mapa em 3D** e permite editar tudo o que ele tem:
  - módulos (pontos de início, kits médicos, bandeiras, bombas, carros, portas…), props, malhas, luzes, decals, neblina, céu, música;
  - toda alteração pode ser desfeita (Ctrl+Z).
- **Cria mapas novos** de três formas:
  - **do zero**: chão e paredes, em qualquer modo de jogo;
  - **a partir do Counter-Strike 1.6**: `.bsp` / `.rmf`, com suas texturas (`.wad`), colisão, pontos de início, locais de bomba e a luz do CS;
  - **a partir de Torrente, el juego**: modelos, mapas e cenas inteiras, convertidos para o Online.
- **Tem os 4 modos de jogo**:
  - Deathmatch (DM), Deathmatch por equipes (DMT), Capturar a bandeira (B) e Destruir o alvo (DO, com locais A e B);
  - opções do DO: tempo da bomba, HUD, radar;
  - armas por mapa, tempo de reaparecimento dos kits médicos e clima (chuva / tempestade).
- **Ferramentas de construção**:
  - formas e sólidos com colisão, percursos, pincel de objetos, medição;
  - edição de colisão, pintura de faces, importação de OBJ, peças reutilizáveis.
- **Verificações antes de jogar**:
  - verificação do mapa, teste de percurso com a colisão real, buscador de quedas e armadilhas;
  - verificação dos pontos de início, equilíbrio das equipes, simulação de partida, mapa de carga.
- **Compartilhar mapas**: exporta um mapa em `.zip` e instala um `.zip` sem nunca sobrescrever arquivos do jogo. Seus salvamentos ficam num histórico de 10 passos.
- **Idiomas da interface**: inglês, espanhol e português. O editor pode **procurar versões novas no GitHub** e se atualizar sozinho.

### Instalar e abrir
1. Baixe o último release e descompacte a **pasta inteira**, por exemplo em `E:\Juegos\Torrente On-Line\tools\VToyEditor`.
2. Abra `VToyEditor.exe`.
3. Na primeira vez, escolha o `demo.vpk` do jogo (ou uma pasta já descompactada). Ele é descompactado uma única vez em `<nome>_unpacked`.
4. Escolha o idioma em **Idioma**.
5. Suas opções ficam em `vtoy_editor.json`, ao lado do `.exe`.

A partir do código (Python 3.10–3.13): `pip install -r requirements.txt` e depois `python run_editor.py`. Para gerar o `.exe`: `build_exe.bat`.

### Primeiros passos
| Quero… | Onde |
|---|---|
| Abrir um mapa | *DEBUG → Lista de cenas* → **Carregar cena** |
| Voar / olhar | **Alt** = voo livre (WASD, mouse); no modo edição, **segure o botão direito** para olhar |
| Selecionar / mover / girar | ferramentas **1–4** (Selecionar, Mover, Girar, Escalar), ou **G** / **R** / **T** + mouse |
| Um mapa novo do zero | *Ferramentas do mapa → Construir → Mapa novo do zero* |
| Um mapa novo do CS 1.6 | *Arquivo → Mapa novo a partir de CS 1.6 (.bsp / .rmf)…* |
| Usar Torrente, el juego | *Arquivo → Pasta de Torrente, el juego…*, depois *DEBUG → Library* |
| Verificar o mapa | *Ferramentas do mapa → Verificar → Verificar mapa* (também roda sozinha a cada salvamento) |
| Testar no jogo | *Arquivo → Salvar, empacotar e testar no jogo* |
| Compartilhar | *Arquivo → Exportar este mapa como .zip* / *Instalar mapa de zip…* |

### Atalhos principais
| Tecla | Ação |
|---|---|
| Alt | voo livre sim / não (Esc volta ao modo edição) |
| W A S D, Shift | mover-se, mais rápido |
| Espaço / E, Ctrl / C | subir, descer (voo livre) |
| 1 … 9 | ferramentas: Selecionar, Mover, Girar, Escalar, Caneta, Preencher, Medir, Colisão, Pintar faces |
| G / R / T + mouse | mover / girar / escalar a seleção (roda: altura / rolagem) |
| Q | copiar a seleção (a cópia segue o mouse) |
| Del | apagar a seleção |
| H / Shift+H | ocultar a seleção / mostrar tudo |
| Ctrl+Z / Ctrl+Y | desfazer / refazer |
| Ctrl+P | busca de comandos (e seus próprios atalhos) |
| F1 | painel de informações sim / não |
| F11 / F12 | tela cheia / captura de tela |

### Bom saber
- **Nada do jogo é sobrescrito.** O que é importado com nome repetido entra com outro nome, e instalar um mapa pula os arquivos que o jogo já tem.
- **Copie também as DLL do modo.** Mapas DO, ou com armas / clima próprios, usam sua DLL do modo. Ela vem no `.zip` do mapa e vai na pasta do jogo do servidor **e** de cada jogador.
- **FPS baixo?** Faça o editor usar a placa de vídeo dedicada (Windows → Configurações de gráficos).
- **Problemas?** Veja o `vtoy_editor.log`, ao lado do `.exe`.

---

*VToyEditor Plus+ · Lahrenheit · https://github.com/Lahrenheit/VToyEditorPlus · Based on Patoke's VToyEditor*
