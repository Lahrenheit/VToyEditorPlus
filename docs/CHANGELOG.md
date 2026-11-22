# VToyEditor Plus+ — Historial técnico y de cambios (español)

Este archivo es el README técnico anterior: todas las secciones numeradas (§1 … §119) con el detalle de cada función, cada arreglo y cada mapa entregado. Las secciones nuevas se agregan al final. El resumen de uso está en el [README](../README.md) (inglés, español y portugués) y el manual completo en [Manual_VToyEditorPlus_es.pdf](Manual_VToyEditorPlus_es.pdf).


Visor y editor de escenas del motor **Virtual Toys** (serie *Torrente*) para **Torrente Online**, portado de C# a Python.
Lee y reescribe byte a byte todos los formatos del juego, dibuja las escenas en 3D (OpenGL), permite editarlas, reempaquetar el
`demo.vpk` y reutilizar objetos, texturas y mapas de **Torrente, el juego** (motor más viejo) para crear mapas nuevos.

> **Estado:** la lectura/escritura de formatos, la lógica del editor, el importador y el conversor están probados con los archivos reales
> (ver *Tests*). La parte gráfica (OpenGL + ImGui) se verificó con un test de humo con GL simulado, no en una GPU: si algo falla al
> abrirlo, mirá `vtoy_editor.log`.

---------------------------------------------------------------------------------------------------------------------------

## 1. Instalación
```
pip install -r requirements.txt        # numpy, Pillow, glfw, PyOpenGL, imgui-bundle
python -m vtoy.app                     # abre un selector: elegí demo.vpk (o una carpeta ya desempaquetada)
python -m vtoy.app demo.vpk mp_dm_plaza.scn
python -m vtoy.app juego/ --library "Torrente el juego"/
```
- Si elegís un **`.vpk`**, se desempaqueta la primera vez en `<nombre>_unpacked` (junto al vpk). *File → Repackage VPK* lo vuelve a escribir en el
  mismo `.vpk` y deja una copia `.bak` del original.
- La carpeta del juego debe tener `scns/ nfos/ texs/ keys/`.
- Opciones: `--library <carpeta>` (Torrente el juego), `--vpk-out <archivo>`, `--no-log`.

## 2. Controles
| Acción | Cómo |
|---|---|
| Volar | clic en la vista (captura el mouse) + **WASD**, mouse para mirar, **Shift** rápido, **Espacio/E** sube, **Ctrl/C** baja (Q = copiar, ver §17) |
| Soltar el mouse (usar los paneles) | **Esc** |
| Seleccionar | clic con el mouse capturado: elige lo que está en la mira |
| Mover lo seleccionado | **G** + mover el mouse (sobre el suelo, según hacia dónde mirás); **G** + rueda = subir/bajar |
| Rotar lo seleccionado | **R** + mouse (giro / cabeceo), **R** + rueda = alabeo; **Ctrl** + rueda = giro vertical 5° (Shift = 1°) |
| Pantalla completa | **F11** |

Los movimientos con G/R/Ctrl+rueda se acumulan (la caja de selección se pone naranja y se mueve) y se aplican al soltar, porque
recalcular la escena tarda medio segundo. Funciona con módulos con matriz, props (mover y rotar), mallas (solo mover) y puntos de inicio.

## 3. Interfaz
**Arriba a la izquierda:** FPS, *Position* (coordenadas **del motor**, las mismas de los campos `position` de los módulos) y *Angles* de la cámara.

**Panel DEBUG** (todo junto, como el editor original):
- *Save scene* (guarda `.scn` y, si cambió, el `.opt`), *Repackage VPK*, *Reload file system*.
- Casillas de depuración: collision boxes, debug depth test, start/spawn points, health packs, flag objects.
- *Scene list* / *Maps list*: cargar otra escena (*Load Scene*) o cambiarle el mapa a la escena actual (*Load Map*).
- *Lights* y *Decals*: agregar, borrar (botón X) y editar cada uno (posición, dirección, rangos, colores, textura, escala...).
- *Library: Torrente, el juego*: importar modelos, importar mapas y convertir escenas (ver sección 6).
- *Scene*: niebla (cercana, lejana, color), cámara (near/far) y el árbol de **Modules** (agregar, ver, editar, duplicar, borrar).
- *Selection*, *View options* (culling, decales, niebla, orden de transparencias, gamma, velocidad de cámara, fov).
- Los últimos mensajes del log aparecen arriba del panel.

**Cada módulo con modelo** muestra: `position`, `rotation (deg)`, `scale` (arrastrar, o Ctrl+clic para escribir el valor), `model_name`
(texto libre o **Choose model...** con buscador), campos propios del módulo, y los botones *Select*, *Move here* (lo pone donde está la cámara),
*Go to* (lleva la cámara hasta él), *Duplicate*, *Delete*. La rotación/escala solo reescriben la matriz si las tocás.

**Ventana Scene Textures:** miniaturas de las texturas de la escena; clic = ver datos; *Export PNG* y *Replace from PNG* (reconvierte a `.tex`).

**Ventana Models (.nfo):** todos los modelos del juego con filtro; clic = se ve en 3D delante de la cámara (caja celeste);
*Place as <tipo>* lo agrega a la escena; *Re-place here*; *Hide preview*. Con el selector **module type** la lista muestra solo los modelos que ese tipo de
módulo usa en las escenas existentes (ej. `mp_CCar` → corsa, galloper, coche_lujo...; `mp_salud` → ITEM_Medikit...). El formato no dice qué
modelo admite cada módulo, así que esto se **aprende de las escenas** (`vtoy/catalog.py`); con "all models" se puede elegir cualquiera.

## 4. Qué hace el programa (resumen de funciones)
- Abrir `demo.vpk` (desempaquetar) y reempaquetar una carpeta en un `demo.vpk` (con backup).
- Ver cualquier escena: mallas del mapa, props, decals, módulos con modelo (RenderNFO, AnimatedRenderNFO, mp_CCar, mp_Door, mp_salud, mp_Flag, cglass,
  mp_Boton, mp_Moto, VagonMetro, Ventilador, ToroCar, mp_Bomba, mp_BombZone...), niebla, transparencias bien ordenadas.
- Editar: módulos (alta/baja/duplicado/campos/matriz), props, mallas (mover), luces, decals, niebla, cámara, mapa de la escena.
- Texturas: ver, exportar a PNG, reemplazar desde PNG (DXT1/DXT5, con o sin mipmaps).
- Modelos `.nfo`: leer (mallas, materiales, huesos/skin), exportar a OBJ, previsualizar en 3D.
- Animaciones `.key`: leer/escribir.
- Catálogo módulo → modelos, autoaprendido.
- Compatibilidad con **Torrente, el juego**: texturas `TeX1`, escenas viejas, importador sin pisar nada y conversor de escenas a Online.
- Log a archivo, F11, `.exe` con auto-py-to-exe.

## 5. Formatos soportados (todos con round-trip byte a byte verificado)
| Extensión | Contenido |
|---|---|
| `.vpk` | paquete `vtPack` |
| `.scn` (`VTS1`) | escena: descriptor (mapa, heightmap, niebla, cámara, música) + módulos. Acepta el descriptor corto y los datos finales de las escenas viejas |
| `.opt` (`VTOP` / `VTO1`) | mapa: mallas, props, decals, luces, cajas. Bloques sin decodificar (hulls, sectores) se conservan tal cual |
| `.hm` (`VTHM`) | heightmap en quadtree |
| `.nfo` (`VTFF`) | modelo: nodos, materiales, mallas, skin |
| `.key` (`FKEY`) | animaciones por nodo + eventos |
| `.tex` (`TeX2`) | DXT1 / DXT5 |
| `.tex` (`TeX1`) | RGB24 / ARGB32 sin comprimir (Torrente, el juego); se convierte a TeX2 al importar |

## 6. Usar Torrente, el juego
1. Desempaquetá los `.7z` en una carpeta con `nfos/ texs/ keys/ scns/` (`python tools/vtoy_cli.py un7z archivo.7z carpeta`; las texturas vienen en volúmenes
   `.7z.001/.002/.003`: unilos antes con `copy /b`). **No los copies encima de la carpeta de Online** (565 texturas tienen el mismo nombre y se pisarían).
2. Abrí el editor con `--library carpeta` o desde *DEBUG → Library → Browse*.
3. En *Library* elegí qué mostrar:
   - **models (.nfo):** *Import and place in scene*: copia el modelo con sus texturas a tu juego y lo agrega como módulo.
   - **maps (.opt):** *Import map and create scene*: copia el mapa, el heightmap y las texturas y crea una escena nueva con un punto de inicio.
   - **old scenes (convert):** *Convert to an Online scene* (ver abajo).

**Reglas del importador** (nada de Online se sobrescribe): TeX1 → TeX2 (DXT5 solo si hay alpha, porque el `vtKernel.dll` de Online no lee TeX1);
si ya existe lo mismo (misma imagen / mismo archivo) se reutiliza; si existe con el mismo nombre pero es distinto, el viejo se importa como `tj_<nombre>` y el
modelo/mapa se reescribe para apuntar a él.

### Convertir un mapa de Torrente, el juego a Torrente Online (ej. Spinelli chalets)
En el juego viejo un "mapa" es una **escena** (`.scn`) cuyo nivel (`.opt` + `.hm`) lo carga el DLL del nivel. Para pasarlo a Online hace falta: (1) el nivel y sus texturas
en formato que Online lea, (2) una escena Online que lo use, (3) los objetos de la escena traducidos a módulos de Online.
```
python tools/vtoy_cli.py convert-scene "Torrente el juego" juego fasex_f03 spinelli_chalets_online
```
(o en el editor: *Library → old scenes (convert)* → elegir `fasex_f03.scn` → nombre → *Convert to an Online scene*). Spinelli chalets es `fasex_f03.scn`
(`spinelli_chalets.opt` + `.hm`). Qué hace:
1. Importa el nivel (`.opt` + `.hm`) y todas sus texturas (TeX1 → TeX2), sin pisar nada.
2. Crea `scns/<nombre>.scn` copiando los ajustes de una escena Online (niebla, módulo principal `mp_deathMatch.dll`; usa la escena abierta o el primer `mp_dm*`).
3. Traduce módulos: `RenderNFO`/`AnimatedRenderNFO` (mismo formato, con sus modelos, texturas y animaciones `.KEY`), `CCar`→`mp_CCar`, `salud`→`mp_salud`,
   `SoundSource`→`mp_SoundSource`; los módulos "decorativos" (PhysicsModel, Obstaculo_*, CommonItem...) pasan a `RenderNFO` estáticos.
4. Pone **14 puntos de inicio** (`mp_CStartPoint`, 2 equipos) en círculo alrededor de donde estaba el jugador (`CTorrente`) y un `mp_CameraStartPosition`.
5. Imprime un informe: lo copiado, reutilizado y renombrado, y los módulos **no convertidos**.

**No se convierte** (es código del juego viejo, no existe en Online): enemigos (`Enemy1`), peatones, perros, armas y munición, físicas, scripts y la lógica del DLL del nivel.
Después de convertir, abrí la escena en el editor, acomodá los puntos de inicio, agregá puertas, botiquines, banderas, etc. desde *Models (.nfo)* y guardá/empaquetá.
Notas: los `.wav` de los `SoundSource` no vienen en los archivos del juego viejo (verificá que existan en Online); no probé el resultado dentro del juego Online real.

## 7. Línea de comandos (`tools/vtoy_cli.py`)
| Comando | Qué hace |
|---|---|
| `unpack demo.vpk carpeta` / `pack carpeta demo.vpk` | desempaquetar / empaquetar vpk |
| `un7z archivo.7z carpeta` | extraer `.7z` (Python puro; LZMA, LZMA2, BCJ, BCJ2) |
| `tex2png`, `png2tex [--fmt dxt1\|dxt5] [--mips]` | convertir texturas |
| `nfo2obj modelo.nfo salida.obj` | exportar un modelo a OBJ |
| `info escena.scn` | listar los módulos de una escena |
| `import-model` / `import-map` `<biblioteca> <juego> <nombre>` | importar de Torrente, el juego |
| `convert-scene <biblioteca> <juego> <escena> <nuevo> [--template escena_online]` | convertir una escena vieja a Online |
`tools/preview.py` dibuja modelos/mapas en CPU a PNG (sin GPU).

## 8. Crear el .exe (auto-py-to-exe)
Lo mismo que hace `build_exe.bat`, con la ventana de auto-py-to-exe (Python 3.10–3.13):
1. En la carpeta del editor: `pip install auto-py-to-exe -r requirements.txt` y después `auto-py-to-exe`.
2. **Script Location:** `run_editor.py`.
3. **Onefile:** *One Directory*. **Console Window:** *Console Based* (muestra los errores; cuando todo ande podés pasar a *Window Based*, el log `vtoy_editor.log` se sigue escribiendo igual).
4. **Icon:** `icon\vtoy.ico` (o el tuyo).
5. **Additional Files → Add Folder** (las tres carpetas, con el destino tal cual):
   * `vtoy\app\shaders` → `vtoy/app/shaders`
   * `vtoy\language` → `vtoy/language`
   * `icon` → `icon`
6. **Advanced:**
   * `--name`: `VToyEditor`
   * `--collect-all`: `imgui_bundle` y `glfw` (una entrada cada uno)
   * `--collect-submodules`: `vtoy.language`
   * `--hidden-import`: `OpenGL.platform.win32` y `OpenGL.GL`
   * `--version-file` (opcional): `version_info.txt`
   * (opcional, música .ogg) si tenés `pygame-ce` instalado: `--collect-all pygame`
7. **CONVERT .PY TO .EXE**. Queda en `output\VToyEditor\`: copiá **la carpeta entera** (el .exe solo no anda), por ejemplo a `E:\Juegos\Torrente On-Line\tools\VToyEditor`. Tu `vtoy_editor.json` (opciones, candados, sólidos…) está al lado del .exe: no lo borres al reemplazar.
8. En *Settings* (abajo) está **Export Config to JSON File**: guardalo y la próxima vez lo cargás con *Import Config From JSON File*.

## 9. Log y errores conocidos
- Se crea `vtoy_editor.log` junto al `.exe` (o donde ejecutes) con todo lo impreso y los errores completos; también en versiones sin consola. `--no-log` lo desactiva.
- `error C6020: Constant register limit exceeded` (GPU NVIDIA): el shader tenía 128 luces; ahora son 32 (`MAX_LIGHTS` en `vtoy/app/shaders/scene_shader.vert`). Si compilás el `.exe`, incluí la carpeta `shaders` actualizada.
- Las escenas de Torrente, el juego se pueden **abrir para verlas** (el mapa se resuelve por el DLL del nivel, tabla en `vtoy/legacy.py`), pero sus módulos (Enemy1, Peaton...) no existen en Online.

## 10. Problemas del editor original (C#) resueltos
- *Banderas semitransparentes bajo el suelo de la iglesia (plaza):* los triángulos transparentes se ordenan de atrás hacia delante por centroide en espacio mundo (los grandes se subdividen), sin pre-pass de profundidad.
- *Módulos sin modelo:* se parsean los `.nfo` y se dibujan RenderNFO, AnimatedRenderNFO, mp_CCar, etc.
- *Sin edición:* ahora se pueden mover props y mallas, y editar luces, decals y módulos; guardar `.scn`/`.opt` y reempaquetar.

## 11. Limitaciones
- Sin decodificar (se conservan tal cual al guardar): hulls y sectores del `.opt`, parte final del `.scn`, `mp_Generador`, `CParticleSystem`, `mp_LightControl`, matriz OBJ1 de los `.nfo`, framerate de `.key`.
- Mover una malla no recalcula el bloque de sectores `VTO1`; no se edita geometría vértice a vértice ni se reescriben animaciones.
- La iluminación se dibuja sin luces (las luces se editan pero no sombrean el visor).
- Las ventanas no se pueden sacar fuera de la ventana principal (limitación del backend glfw de Python).
- No hay miniaturas de modelos, solo la vista previa 3D de uno por vez.

## 12. Estructura del código
```
vtoy/            binutil, scn, modules, opt, hm, tex, nfo, keys, vpk, gamefs   (formatos)
                 catalog (módulo→modelos), legacy (mapas de escenas viejas), importer, convert
vtoy/render/     geometry (bake a numpy, transparencias), camera
vtoy/app/        state (lógica del editor), gl_renderer, ui, editor, __main__, shaders/
tools/           vtoy_cli.py, preview.py, sevenzip_min.py
tests/           test_roundtrip, test_state, test_render_logic, test_editor_smoke, test_import
run_editor.py    lanzador para el .exe
```

## 13. Tests
```
python tests/test_roundtrip.py      # variable VTOY_DATA = carpeta con scns/ nfos/ texs/ keys/ de Online
python tests/test_state.py          # edición, guardado, vista previa, catálogo, rotación
python tests/test_render_logic.py   # orden de transparencias, subdivisión, cámara
python tests/test_editor_smoke.py   # ventana/UI con glfw+OpenGL+imgui simulados
python tests/test_import.py         # Torrente, el juego: TeX1, escenas viejas, importar, convertir (VTOY_TJ_DATA)
```

## 14. Modos de juego, spawns, botiquines y música

Panel DEBUG → **Game mode / spawns / music** (todo se crea donde está la cámara; luego se mueve con G / coordenadas).

| Modo | Módulo principal (`main_module_name`) | Necesita |
|---|---|---|
| DM  | `mp_deathMatch.dll` | ≥ 8 `mp_CStartPoint` (equipo 0/1 indistinto) |
| DMT | `mp_deathMatchTeam.dll` | start points de **ambos** equipos (0 y 1) |
| B   | `mp_CaptureTheFlag.dll` | start points de ambos equipos + 2 `mp_Flag` (equipo 0 amarilla, 1 roja) |
| DO  | `mp_DestroyTheTarget.dll` | muchos start points (~16-38) + 1 `mp_BombZone` (+ `mp_Boton`/`mp_Bomba` opcionales) |

* Elegir el modo en el combo cambia `main_module_name`. El prefijo del archivo (`mp_dm_`, `mp_dmt_`, `mp_do_`, `mp_b_`) es solo convención.
* **Nacimientos**: botones *Start point team 0/1* o *Ring of 14*. El campo `order` se autoincrementa por equipo.
* **Botiquines**: `mp_salud` con `nfos/ITEM_Medikit.NFO` (50) o `ITEM_MiniMedikit.NFO` (25). `health` se edita en el módulo.
* **Banderas / zona de bomba / botón**: se clonan de una escena Online real (su cola binaria no está decodificada).
* **Música**: campo `ambient_music` (combo con las usadas por Online, o texto libre). El `.wav` va en la carpeta `musica/` del juego; no viene en demo.vpk.
* **Check scene** lista lo que falta según las escenas oficiales. Es una inferencia de las escenas existentes, no una prueba en el juego.

## 15. Mapas de Torrente el juego (.opt VTOP) -> Online (VTO1)
Los .opt del juego viejo empiezan con `VTOP`; todos los de Online con `VTO1`. Al importar un mapa (Library) el editor lo convierte
(`vtoy/optconv.py`): vertices por sub-malla, cajas de colision en una lista global, arbol de sectores con la tercera lista (cajas),
luces puntuales radio -> start/end. La conversion se valido contra `mp_dm_comercial.opt`, que es el `comercial.opt` viejo
convertido por los desarrolladores (mallas, indices e hulls identicos). Si ya habias importado un mapa con una version anterior,
borra el `.opt` viejo (`nfos/pista.opt`, etc.) de la carpeta del juego y vuelve a importarlo.

Nota (prueba real): una escena con 5 start points creados a mano (todos del mismo equipo, uno en 0,0,0 fuera del mapa, sin camara ni
botiquines) no cargaba; la misma escena con el anillo de 14 start points (equipos 0/1), camara y botiquines si. Algunas escenas oficiales
tienen solo 2-4 start points, asi que el numero no es lo unico: revisa que todos esten sobre el mapa (Check scene lo avisa).

## 16. Modo edicion, herramientas, pluma de recorte y cielo

**Modos de mouse** (HUD arriba a la izquierda):
* **Edicion (por defecto)**: puntero visible. Boton izquierdo = herramienta activa, **boton derecho mantenido = mirar**, WASD/QE/Shift = volar, rueda/click en los paneles normal. Pasar el mouse sobre un objeto muestra un cuadro con su informacion.
* **Vuelo**: **ALT** captura el mouse (mira con el mouse, mira de puntero la cruz del centro). ALT o Esc vuelve a edicion.

**Barra "Tools"** (atajos 1-6): Select, Move, Rotate/tilt, Scale, Pen, Fill (ver §17).
* Select: click en un objeto -> sus propiedades aparecen en DEBUG > Selection (se abre solo). Los modulos tienen prioridad sobre la geometria del mapa.
* Move: click y arrastra (libre = sobre el piso; o con las manijas de color X rojo / Y verde / Z azul, o manteniendo X/Y/Z). Se aplica al soltar.
* Rotate: eje Y = girar, X / Z = inclinar (pitch / roll). Las manijas de color tambien inclinan. Solo objetos con rotacion (props y modulos con matriz).
* G / R + mouse y Ctrl+rueda siguen funcionando. Del borra el modulo/prop seleccionado; Duplicate duplica un modulo.
* Las posiciones muestran el eje dentro de cada campo (X / Y / Z).

**Pluma (Pen) = recortar mapa**: click en el piso para marcar los puntos (la altura del plano se ajusta con "ground height Y"; Backspace quita el ultimo). Con 3 o mas puntos: "Crop map + scene to outline" deja solo lo que esta dentro (o fuera si se desmarca *keep inside*): se eliminan triangulos de las mallas, props, cajas de colision, hulls, decals y modulos fuera, y se renumeran todas las listas de los sectores para que el motor las lea. "Undo crop" revierte; "Save cropped map as new .opt" guarda con otro nombre (no toca el mapa original) y apunta la escena a el. Limites: el heightmap (.hm) no se recorta; las mallas que algun prop restante usa quedan enteras; el orden/indices se validan con tests pero **no se probo en el juego**.

**Cielo**: en "Game mode / sky / spawns / music", combo con los cielos que usan las escenas de Online (cantidad de escenas) y vista previa; "also copy fog" copia tambien la niebla de una escena con ese cielo.


## 17. Deshacer, mallas, relleno, vista previa y exportacion

**Causa encontrada de los decals/luces perdidos tras recortar**: en los mapas Online `scene_obj_count` = mallas + props + **decals**, y los sectores listan tambien a los decals (indices despues de los props). El recorte anterior los sacaba de las listas y no los contaba, asi que el motor no los dibujaba. Ahora recortar, borrar mallas/props/decals y agregar mallas/props/decals renumeran todo (mallas, props, decals) y los tests lo verifican contra mapas Online reales. (Las luces `Light` no van por los sectores.) *No probado en el juego.*

**Menu superior**: File (Save scene, **Save scene as...** con nombre, **Export this map as .zip**, Map preview), Edit (**Undo Ctrl+Z / Redo Ctrl+Y** globales: escena, mapa, luces y decals; hasta 30 pasos; arrastrar un campo cuenta como un paso), View (cielo, decals, niebla, colision, ventana "Map parts").
* **Save scene as**: guarda `scns/<nombre>.scn` sin tocar la escena de trabajo; si el mapa tiene cambios sin guardar tambien lo guarda con ese nombre (`<nombre>.opt` + `.hm`), asi el original queda intacto.
* **Cielo** visible en la vista (esfera con la textura del cielo de la escena; View > Sky).

**Nombres unicos**: Duplicate / Add module / start points usan nombres unicos sin distinguir mayusculas (`CStartPoint_1`, `CStartPoint_2`...), sin chocar con `StartPoint_<n>` del anillo de 14 spawns. Duplicados = crash al cargar, por eso tambien se avisan al guardar.
**mp_CameraStartPosition**: ahora es un modulo tipado (ojo + punto a donde mira), aparece en "Add new module", se puede borrar y al guardar avisa que debe existir uno.
**Modulos .nfo nuevos**: RenderNFO / AnimatedRenderNFO / mp_Cosa / mp_CCar... se crean con la cola (tail) que usan las escenas Online (una cola vacia hacia crashear el juego al cargar). Los tipos sin cola conocida (botones, BombZone, ventiladores...) copian la de una escena existente.

**Mallas (meshes) y props**: seleccionables y editables como los modulos.
* **G + mouse** mueve, **R + mouse** rota (X/Y, rueda = roll), **T + mouse / rueda** escala, **Ctrl+rueda** gira en Y, **Q** copia y la copia sigue al mouse hasta hacer click (Esc cancela), **Del** borra. Mientras se mueve se ve la caja (rotada / escalada) con el cambio pendiente; se aplica al hacer una pausa o soltar.
* Borrar una malla/prop **borra tambien su colision** (cajas y hulls dentro de su volumen; casilla para desactivarlo) y renumera sectores: las escaleras borradas que seguian chocando eran colision independiente del dibujo. Rotar/escalar una malla compartida por props no se permite (se hace sobre los props).
* La malla copiada/relleno **no copia colision**. Menu View > Collision dibuja las cajas orientadas y los hulls para ver lo invisible.
* Pen: ademas de recortar: "Delete collision inside outline" y "Delete geometry inside outline".

**Fill (6)**: marca puntos en el piso alrededor del hueco, elige textura (lista, o Shift+click en el mapa = gotero) y "Fill polygon" crea una malla plana (triangulacion de orejas, UV por tile) registrada en los sectores. Para rellenar con un elemento existente: seleccionarlo y **Q**.

**Map parts** (View): lista de mallas con triangulos, texturas y props; Go to / Delete; por textura: Extract PNG / .tex, **Replace (esta malla / todas)** con una imagen PNG/JPG/DDS/.tex. La textura importada se guarda como `texs/<escena>__<nombre>.tex` (distinguible por mapa) y solo se cambia en este mapa.

**Vista previa del mapa**: File > Map preview: "Capture current view" o "Capture automatic" (vista aerea), 256x256, se guarda como `texs/<escena>-tbn.tex` (lo que lee el menu del juego; mismo formato DXT con mipmaps que los `*-tbn.tex` oficiales) o como `.dds` a eleccion.
**Exportar un mapa**: File > Export this map as .zip: escena, .opt, .hm, texturas (mallas, decals, cielo, modelos .nfo), modelos, animaciones y la vista previa si existe, con sus rutas relativas (`scns/`, `nfos/`, `texs/`, `keys/`). Guarda antes: se exporta lo que esta en disco.

Cambios de teclas: bajar la camara = **Ctrl o C** (Q ahora copia).
Lo que NO se pudo resolver: el cierre del juego al salir del mapa (no hay forma de reproducirlo sin el juego; compara con una escena oficial: modulos, nombres unicos, camara). Todo lo de esta seccion esta probado con tests y datos reales pero **no en el juego ni con GPU**.


## 18. VToyEditor Plus+ (tercera tanda)

**Arreglos**
* **Move ya no cierra el editor**: si el rayo del mouse no toca el suelo (mirando hacia arriba) el arrastre sigue sin fallar; ademas cualquier error de una herramienta se registra en el log y el editor sigue vivo.
* **R + mouse**: se aplica al soltar la tecla; si el objeto no se puede rotar (malla compartida por props) ahora lo avisa en pantalla (linea amarilla del cuadro de arriba a la izquierda).
* **Show health packs / flags**: al destildar ya no se dibujan los modelos de los botiquines / banderas. Nuevo **Show camera start position** (caja + linea hacia el punto que mira).
* Convertir un mapa de Torrente el juego: el `.opt` (y `.hm`) convertido se llama **igual que la escena nueva**.
* **Escaleras invisibles**: borrar una malla/prop borra la colision dentro de su volumen **y** las cajas de colision que quedaron sin ningun dibujo cerca. Panel Pen: **Find collision without geometry** cuenta esas cajas y **Delete them** las borra (solo cajas; los hulls no se juzgan porque no se conoce su relacion con el dibujo). Si queda alguna, "Delete collision inside outline" las borra a mano. *No probado en el juego.*

**Selection** (click en la vista): posicion, **rotacion XYZ (grados)** y **escala XYZ** editables para props, modulos con matriz y mallas (en mallas compartidas por props se editan los props; las mallas no guardan angulos, se muestran los aplicados en la sesion). **Change texture**: lista filtrable de texturas o un PNG, por material.

**Pen**: UNDO CROP siempre visible (tambien Ctrl+Z), **Delete collision OUTSIDE outline**, **Delete geometry OUTSIDE outline** (solo geometria; no toca spawns ni items), Delete inside (geometria / colision).
**Fill**: los rellenos hechos en la sesion se listan: **Delete**, mover todo el relleno arriba/abajo/izquierda/derecha (paso configurable), altura Y y cada punto editable. Cada cambio reconstruye la malla (puede tardar un instante).

**Clima** (seccion "Weather")
* **Lluvia**: en los `.opt` de Marbella/Moonlight es una malla chica (24 quads con `gota_lluvia`, `gota_salpica`, `GOTA_AGUA_01`) en un sector propio lejos del mapa. El editor copia esa malla y su sector desde `mp_dm_marb.opt` (activar/desactivar, ida y vuelta exacta).
* **Tormenta (preset)**: lluvia + cielo `cielo_war` + niebla oscura de Marbella. Rayos/truenos no existen en los datos de Online, por eso no se ofrecen.
* **Luna**: en Moonlight es un decal `luna` alto en el cielo (escala 2000). Casilla para agregarla/quitarla, posicion y tamaño editables.

**Cielo**: la lista incluye todas las texturas `cielo*` (aunque ninguna escena las use); **Import PNG as sky** convierte un PNG a `texs/cielo_<nombre>.tex` (DXT con mipmaps) y lo asigna; **Export sky as PNG** lo guarda en la carpeta `export`.

**Interfaz**
* Titulo de la ventana: **VToyEditor Plus+**.
* **Movimiento libre solo con ALT** (mira con el mouse, WASD en la direccion de la mirada, Espacio/E sube, Ctrl/C baja). En modo edicion WASD solo camina en plano (sin subir ni bajar).
* Cerrar la ventana con cambios sin guardar pregunta: **Save and exit / Exit without saving / Cancel**.
* Cuadro de arriba a la izquierda: agrega las teclas del modo libre; **F1** lo oculta / muestra. Debajo: **CREANDO MAPA: NOMBRE** (escenas nuevas / convertidas / guardadas como) o **MODIFICANDO MAPA: NOMBRE**.
* Vista previa del mapa: marco amarillo con el area exacta que se captura (cuadrado central de la vista).
* Al abrir se carga el **ultimo mapa** usado (`~/.vtoy_editor.json`); si no existe, el primero por orden alfabetico.

Todo probado con tests y datos reales, **sin GPU ni el juego**.

**Icono del programa**: poné un `.ico` en la carpeta `icon\` y corré `build_exe.bat`: el .exe usa el primer `.ico` que encuentre (si no hay, usa el de por defecto). La carpeta `icon` se incluye en el paquete y la ventana del editor usa ese mismo archivo (o un `.png`) como icono. **Barra de tareas** (§33): en Windows el `.ico` se aplica a la ventana con la API de Windows (tamaño grande para la barra de tareas / Alt+Tab y chico para la barra de título), el `.ico` siempre gana sobre un `.png`, y el editor tiene su propia identidad en la barra de tareas (no se agrupa con python.exe). Una carpeta `icon` al lado del .exe tiene prioridad, así se puede cambiar sin recompilar. Si no hay `.ico`, se usa el icono metido en el .exe.

**Pen / Fill: mover puntos**: click izquierdo sobre un punto ya puesto y arrastrar lo mueve (el radio de agarre crece con la distancia de la camara); click en otro lado agrega un punto nuevo. **Library > maps (.opt) > "Import map and create scene"**: el `.opt` (y `.hm`) importado se llama igual que la escena nueva.


## 19. Cuarta tanda

* **Causa de la colision "fantasma" (escaleras que seguian chocando)**: los *hulls* del `.opt` son poligonos 2D guardados como **(x, z, etiqueta)** (la etiqueta vale -32768 ... 8192, no es una altura). El editor los leia como (x, y, z): al borrar por zona o por malla comparaba con la columna equivocada, asi que casi nunca los borraba, y la vista de colision los dibujaba como lineas verticales naranjas interminables. Corregido: borrar colision (por contorno o al borrar una malla) ahora usa x y z; la vista dibuja los hulls planos al nivel habitual del mapa. *No probado en el juego.*
* **Find collision without geometry**: ahora (margen 10, celda 50) marca las cajas sin dibujo cerca en **magenta**, las lista (centro y tamano) con **Go** (lleva la camara) y **Delete** por caja, y **Delete them** las borra todas. Ojo: las paredes invisibles del borde del mapa tambien aparecen; borra solo las que no quieras.
* **Crop map / scene to outline** ya borra geometria y colision fuera del contorno; se sacaron "Delete collision OUTSIDE" y "Delete geometry OUTSIDE".
* **Pen**: click sobre un segmento del contorno inserta un punto ahi (y queda agarrado para moverlo); click sobre un punto lo mueve.
* **Show camera angle (field of view)**: triangulo verde + linea blanca en cada `mp_CStartPoint` (incluye el anillo de 14) y en `mp_CameraStartPosition` mostrando hacia donde miran. Medido en 1589 start points oficiales: el motor mira hacia (sin angulo, cos angulo) en (x, z). El anillo de 14 que genera el editor estaba mal orientado; ahora mira al centro.
* **Al abrir** carga el ultimo mapa y deja la camara donde estaba al cerrar (se guarda cada 5 s y al salir). Antes el selector de vpk borraba la config y por eso no recordaba el mapa.

## 20. Lluvia / tormenta (corrección)

La lluvia de Marbella **no son decals ni una malla**: la malla `gota_lluvia` que se copiaba antes no produce lluvia (se quitó esa función).
La lluvia la crea el código de la DLL del modo (`AddShower`) **solo si el nombre del mapa es exactamente** `nfos\mp_dm_marb.opt`
(`mp_deathMatch`, `mp_deathMatchTeam`, `mp_deathMatchChalet`), `nfos\mp_b_marb.opt` (`mp_deathMarb`, `mp_CaptureTheFlag`) o
`nfos\mp_b_gotico.opt` (`mp_CaptureChucrch`, `mp_CaptureThehall`, estas dos con rayos).

Weather ▸ **Make rain DLL for this map**: indicás la DLL original del juego (p. ej. `mp_deathMatch.dll`) y se genera
`export/mp_deathMatch_<mapa>.dll`, una copia donde la comparación apunta a `nfos\<mapa>.opt`; el scene pasa a usar esa DLL como
módulo principal. La original no se toca. Hay que copiar la DLL nueva junto a las demás DLL del juego (no reemplazar ninguna).
También: `python -c "from vtoy import dllpatch; dllpatch.patch_map_name(src, dst, r'nfos\mi_mapa.opt')"`.
**Sin probar en el juego** (no tengo el juego): si no carga la DLL o no llueve, avisame qué pasa. Alternativa sin DLL:
nombrar el mapa `mp_dm_marb.opt` en una carpeta propia (reemplaza a Marbella, no recomendado).

## 21. Colisión fantasma por hulls grandes + Browse de la DLL

* Los *hulls* (huellas 2D de colisión) se descartaban solo si su **centroide** caía en la zona borrada. Un hull grande (en Malibu hay
  uno de 830 puntos y otro de 102 que abarcan casi todo el laberinto) tiene el centroide lejos, así que nunca se borraba y seguía
  bloqueando el lugar donde borraste la geometría. Ahora, además, se **cortan los puntos** del hull (si tiene más de 4) que caen dentro de la
  zona borrada (borrar objetos, borrar colisión en la selección, crop) o fuera del contorno (crop outside). Los hulls chicos siguen
  borrándose enteros por centroide.
* Weather ▸ **Browse...** abre el selector de archivos para elegir la DLL del juego.

## 22. Carpeta export, DLL propia y look at de la cámara
* Todo lo que se exporta va a la carpeta **`export`** (antes algunos casos usaban `exports`).
* **Export this map as .zip** incluye, en `dll/`, la DLL principal del scene cuando no es una de las 4 de los modos (p. ej. la copia con lluvia).
* CameraStartPosition: "look at" ahora se edita con **heading / pitch / distance** (grados y distancia) y el vector crudo con paso 50.
* Los triángulos de dirección son más chicos (150 en spawns, 250 en cámara).

## 23. Quinta tanda
* **Idiomas**: Language ▸ English / Español / Português. Cada idioma es un archivo en `vtoy/language/` (`en.py`, `es.py`, `pt.py`); para uno nuevo copiá `en.py`, cambiá `NAME` y traducí `TEXT`. `python tools/extract_strings.py --check` lista lo que falta.
* **Ajustes** en `vtoy_editor.json` (junto a `imgui.ini`): `language`, `export_dir`, `restore_last_scene`, `restore_last_view`.
* **Música**: la lista incluye los `.ogg` / `.wav` de la carpeta `musica` del juego (junto a demo.vpk); *Import music* copia un `.ogg`/`.wav` ahí y lo asigna; el zip exportado lo incluye en `musica/`. También podés escribir el nombre del `.ogg` en *Music file*.
* **Objetos animados**: el helicóptero de `mp_dm_asalto` (y el gramófono, el yate...) no usan ninguna DLL editada: son módulos RenderNFO / AnimatedRenderNFO cuya cola nombra un `.KEY` (`varios\Reposo_helicoptero.KEY`). Al colocar un modelo se asigna solo el `.KEY` que le corresponde (mismo nombre, `Reposo_<nombre>`, `<nombre>_anim`...), y en las propiedades del módulo hay un selector **animation (.KEY)** para cambiarlo o quitarlo. (La hélice sonora del helicóptero es un módulo `mp_SoundSource` aparte.)
* El nombre de la textura de un decal se edita en un borrador y se aplica al salir del campo.
* El `.exe` lleva datos de versión (`version_info.txt`): VToyEditor Plus+, v1.0, Lahrenheit, https://github.com/Lahrenheit.

## 24. FPS bajos: usar la tarjeta gráfica dedicada
Al iniciar, `vtoy_editor.log` dice `OpenGL renderer: ...`; si aparece Intel / UHD, el editor corre en la gráfica integrada.
Windows 11 ▸ Configuración ▸ Sistema ▸ Pantalla ▸ Gráficos ▸ agregar `VToyEditor.exe` (o `python.exe`) ▸ Opciones ▸ **Alto rendimiento** (la NVIDIA).
Panel de control de NVIDIA ▸ Administrar configuración 3D ▸ Configuración de programa ▸ elegir el exe ▸ procesador **NVIDIA de alto rendimiento**.
En el editor: *transparent sort = per texture* y ocultar colisión / decals suben los FPS en mapas grandes.

## 25. Reproducir música y animaciones (.KEY)
* **Game mode / sky / spawns / music ▸ Play music / Stop music**: reproduce la pista elegida (la busca en la carpeta `musica` del juego). Usa `pygame` si está instalado (`pip install pygame-ce`, opcional: `requirements-audio.txt`, NO está en `requirements.txt` porque en Python muy nuevos no tiene wheel y rompe el .bat; reproduce `.ogg` y `.wav`), luego `miniaudio`, y en Windows MCI / winsound (sin instalar nada sirven los `.wav`; los `.ogg` dependen de un códec de Windows). Si no puede, el panel dice qué falta.
* **Módulo con modelo ▸ Play animation / Stop animation + speed**: dibuja el modelo animado con su `.KEY` (la copia estática se oculta mientras tanto). Convención verificada con los archivos del juego: la pose de un nodo es la **inversa** de su matriz respecto al padre, cuaternión `(w, x, y, z)`; en el frame 0 coincide con la pose original del NFO (gramofono, grúas, portones, botones de la plaza, rotor, vagones...). Se asumen 30 frames por segundo (ajustable con *speed*). Los modelos con huesos (skin) se mueven de forma rígida por nodo.
* Si el `.KEY` no corresponde a ese NFO (p. ej. `Yate_Helicoptero.KEY` en `Helicoptero.NFO`: solo 3 de 35 nodos coinciden) la animación casi no se ve: elegí otro en *animation (.KEY)*.

## 26. Sonido del helicóptero, ParedT, música .ogg, Python 3.13
* **Helicóptero con sonido**: en `mp_dm_asalto` el sonido es un módulo `mp_SoundSource` aparte (`Helices_N`, `wavs\HELICOPTERO.wav`, misma posición que `helicoptero_N`, sin loop-flag, máx 4448 / mín 25). Al colocar `Helicoptero.NFO` se crea solo ese sonido (y su animación `.KEY`). En las propiedades de cualquier módulo con modelo hay **Add sound here** (pone un SoundSource en su posición; para el helicóptero usa `HELICOPTERO.wav`). El sonido no sigue al modelo: si lo movés, movelo junto con su `Helices_N`.
* **Show ParedT.nfo (wall)** (debajo de *Show camera angle*): oculta/muestra los módulos cuyo modelo es `paredT.NFO` (paredes de mp_Door / mp_Cosa) para ver mejor el mapa. Solo afecta a la vista del editor.
* **Música**: la lista solo muestra los `.ogg` de la carpeta `musica` (los `.wav` ya no aparecen; igual se pueden importar).
* **Python recomendado: 3.13** (las librerías ya tienen versión compilada). `build_exe.bat` avisa si usás otra.

## 27. Barcos gemelos (capturar la bandera 16 vs 16)
Sección **Twin ships (capture the flag)** (cargá `mp_b_loveboat`, o una copia): crea el mapa con **dos barcos paralelos** unidos por **3 pasarelas de madera**.
* **Copia de región** (`vtoy/regioncopy.py`, usable para otros mapas): duplica mallas, props, decals, luces, cajas de colisión y hulls de una caja, desplazados, y los anota en los **sectores hoja** (solo las hojas del árbol de sectores guardan listas; ahora todas las altas de objetos usan solo hojas). El árbol de sectores del mapa termina en x ≈ 2567, por eso el segundo barco va al **oeste** (si queda fuera, el editor lo rechaza: el juego no lo dibujaría ni tendría colisión).
* **Equipos**: barco original (este) = **amarillo**, copia (oeste) = **rojo**; cada bandera va a la **popa** (extremo redondeado, +z) de su barco; 16 spawns por equipo (configurable) sobre su barco, usando las posiciones originales del barco y extras desplazados. Se duplican botiquines, cristales, personajes, sonidos y paredes (ParedT) para el segundo barco.
* **Pasarelas**: plano de `tablones.tex` + caja de colisión, y se abren huecos en las cajas largas de las barandas (colisión) donde aterrizan. La baranda visible queda, pero se atraviesa.
* **Color**: se crean texturas nuevas `METAL-loveboat_rojo/_amarillo.tex` y `loveboat-01_rojo/_amarillo.tex` (solo cambian la banda violeta del casco y los paneles verdes; blancos, puertas y carteles quedan) y las mallas de cada barco apuntan a las suyas. Las originales no se tocan.
* Un solo paso de *Undo* deshace todo (las texturas nuevas quedan en `texs/`).
**Sin probar en el juego.** Para ponerlo en juego exportá el mapa (carpeta `export`) y probá; si se cierra al cargar o falta colisión en algún punto, decime dónde.

## 28. Renombrar mapa (p. ej. `mp_b_piratas`)
Panel de archivo → **Rename map...** Copia la escena, el `.opt`, el `.hm` y la miniatura `texs/<nombre>-tbn.tex` con el nombre nuevo y sigue trabajando sobre la copia. Los originales no se tocan (otras escenas los comparten).
Dependencias del nombre que se actualizan: campos `map` y `heightmap` de la escena (`nfos\mp_b_piratas.opt/.hm`), nombre de la escena, miniatura, nombre del zip de exportación y, si la DLL del modo tiene el chequeo de lluvia, una copia `<DLL>_mp_b_piratas.dll`.
Ojo: el prefijo `mp_b_` define el modo (capturar la bandera); conviene mantenerlo. Si la DLL del modo (`mp_CaptureLoveboat.dll`) contiene el nombre viejo del mapa, el editor avisa con un WARNING (no se puede reescribir con seguridad); no se pudo verificar sin esa DLL.

**Nota (§28):** *Save scene as...* ahora hace lo mismo que *Rename map...*: guarda escena, `.opt`, `.hm` y miniatura `-tbn` con el nombre elegido (siempre, no solo si hay cambios sin guardar).

## 29. Barcos gemelos: piso (.hm), pasarelas y vista previa
* **El piso del juego sale del `.hm`**, no del `.opt`. Antes solo se copiaban mallas y cajas de colisión, así que el barco rojo no tenía piso y los personajes caían. Ahora *Make twin ships* también copia al barco B las caras de piso del `.hm` (`vtoy/hmcopy.py`), amplía el fondo marino y **reconstruye el árbol de sectores** del `.hm` para que cubra el barco nuevo. Cada pasarela recibe además su propia cara de piso (a la altura de los tablones), así que se puede cruzar.
* El `.hm` editado queda en memoria y se escribe al **guardar el mapa** (o con *Save scene as* / *Rename map*): se crea `<escena>.hm` y la escena apunta a él; el `.hm` original compartido (`mp_dm_loveboat.hm`) nunca se pisa. *Undo* también lo deshace.
* Si ya habías generado los barcos con la versión anterior, ese mapa tiene el `.hm` sin el barco B: cargá de nuevo la escena original (`mp_b_loveboat`), apretá *Make twin ships* y guardá.
* **Vista previa del mapa (File > Map preview)**: se captura con el renderizador real (texturas, cielo, niebla); el crash venía del recuadro amarillo de la guía (§35). Si la captura OpenGL fallara, se dibuja por CPU (`vtoy/render/cpu_capture.py`, aproximado) en vez de cerrar el editor. "Capture automatic" encuadra la zona de aparición de los jugadores. Los colores salen de las texturas (aprox., una muestra por triángulo).

## 30. Candados en los módulos
En la lista **Modules** cada módulo tiene un candado a la izquierda (y ahora muestra también su nombre de objeto):
* **Abierto (gris)** = editable. **Cerrado (naranja)** = bloqueado: no se puede seleccionar en la vista 3D (el clic lo atraviesa y toma lo que está detrás), ni mover, rotar, escalar, editar sus campos o borrar. Sí se puede usar *Go to* para ir hasta él, y *Duplicate* da una copia desbloqueada.
* Clic en el candado para cambiarlo. **Lock all / Unlock all** para todos.
* Los candados se guardan por mapa en `vtoy_editor.json` (`"locks"`), no en los archivos del juego; *Save scene as* / *Rename map* los pasan a la copia. Los módulos nuevos empiezan desbloqueados.
* **Mallas y props también tienen candado.** En la ventana DEBUG, sección **Map Mesh**: lista de todas las mallas del mapa (`#índice`, triángulos, texturas, cuántos props la usan) con su candado, filtro por textura o `#índice`, *Lock all / Unlock all*, clic = seleccionar, doble clic o *Go to mesh* = llevar la cámara. Debajo, **Props (instances of meshes)** con lo mismo. En la sección *Selection* también aparece el candado de la malla/prop elegida; bloqueada, sus campos y su textura quedan en gris.
* Las mallas no tienen nombre: el candado las reconoce por su posición y tamaño (sobrevive a recargar el mapa y a que cambien los índices). Si movés una malla desbloqueada y después la bloqueás, vale la posición nueva.

## 31. Barcos gemelos: escaleras sin colisión y bandera agarrada al empezar
* **Escaleras / pisos chicos sin colisión**: el árbol del `.hm` que armaba el editor tenía los 4 hijos de cada sector en otro orden que los archivos del juego (el juego usa: x baja/z alta, x alta/z alta, x baja/z baja, x alta/z baja). El juego buscaba el piso en el cuadrante equivocado: los pisos grandes (cubiertas) igual aparecían, los chicos (escalones) no. Corregido, y ahora se usa también la misma regla de división (más de 9 caras) y la misma profundidad del mapa original: reconstruir el `.hm` original da hoja por hoja el mismo árbol que el del juego.
* **Mapas ya hechos**: panel *Twin ships* → **Rebuild floor collision (.hm) of twin ships** (con la misma separación que usaste) y guardá el mapa. Rehace el `.hm` desde `mp_dm_loveboat.hm` sin tocar el resto de tus cambios.
* **"¡Llevas la bandera!" al nacer**: el mapa original usa `mp_CaptureLoveboat.dll`, una DLL propia del Love Boat que probablemente tiene la posición de las bases/banderas originales metida adentro. Ahora *Make twin ships* pone la DLL estándar `mp_CaptureTheFlag.dll` (opción marcada por defecto), y hay un botón **Use mp_CaptureTheFlag.dll** para mapas ya hechos. Sin probar en el juego.
* Arreglado: *Make twin ships* mostraba "twin ships failed" aunque había funcionado.

## 32. Pasarelas transitables: rampa – pasarela sobre la baranda – rampa
El costado del barco es una pared (cubierta y -107 → borde y -15) más una baranda hasta y 30, y el `.hm` también tiene esas paredes: una tabla a la altura de la cubierta chocaba con el borde. Ahora cada una de las 3 pasarelas es:
* una **rampa** de tablones (`tablones.tex`) sobre la cubierta del barco amarillo que sube hasta el borde,
* una **pasarela plana** apenas por encima de la baranda (y ≈ 38) de pared interior a pared interior,
* otra **rampa** que baja a la cubierta del barco rojo.
Todo con su piso en el `.hm` (las rampas son caras inclinadas, como las escaleras del juego). Las alturas y bordes se miden del `.hm` del mapa (inclinación ≈ 32°, rampas de ≈ 230 de largo).
**Mapa ya hecho**: panel *Twin ships* → **Rebuild gangplanks (ramps over the rails)** (misma separación que usaste) y guardá: saca las tablas viejas y sus cajas de entre los barcos, pone las nuevas y rehace el `.hm`.

## 33. Icono en la barra de tareas
La barra de tareas no muestra el icono del archivo .exe sino el de la **ventana**. Antes la ventana tomaba el primer archivo de `icon\` por orden alfabético (un `.png` viejo le podía ganar al `.ico`) y se lo pasaba a glfw en un solo tamaño. Ahora ver la nota de la sección de *Icono del programa*. Si sigue viéndose el viejo: desanclá el acceso de la barra de tareas y volvé a anclarlo (Windows guarda los iconos en caché).

## 34. Cajas al pie de la pasarela del medio
Las pilas de cajas (props 41–56 = malla `#43`, con sus cajas de colisión 24–39) estaban en el camino de las rampas del medio. Panel *Twin ships* → **Move the crates by the middle gangplank 5 m (both ships)**: mueve 5 m hacia proa (−z) las 4 pilas (los dos costados de los dos barcos), con su colisión y anotadas en los sectores de su nuevo lugar. Los mapas nuevos ya salen así. Apretarlo otra vez no hace nada (ya no hay cajas en esa zona).

## 35. Map preview
El cierre del editor al abrir *Map preview* era el recuadro amarillo de la guía (argumentos de `add_rect` en un orden que imgui-bundle no acepta). Corregido; la captura vuelve a usar el renderizador del editor (sale igual que la vista, con texturas) y el dibujo por CPU queda solo como respaldo.

## 36. Capturas de pantalla
**File → Screenshot (full resolution)** o **F12**: guarda la vista 3D tal cual se ve, a la resolución real de la ventana (en pantalla completa = la del monitor), sin los paneles del editor, como PNG en `screenshots\<mapa>_<fecha>_<hora>.png` (carpeta al lado de demo.vpk). **File → Open screenshots folder** la abre. Lo que el editor dibuja en la vista (cajas de spawns, selección, colisión) sale en la foto si está activado: apagalo en *View* / DEBUG antes si querés la imagen limpia.

## 37. Bases (pedestales) de bandera
En `mp_b_anderguater` las banderas están sobre un pedestal que es **parte del mapa** (malla del `.opt` con textura `bandera y pedestal.tex`, uno rojo y uno amarillo) más su piso en el `.hm` (se puede subir). En `mp_b_garaje` / `mp_b_almacen` son plataformas del propio escenario.
* Panel *Twin ships* → **Add bases under the flags**, o en los campos de un módulo `mp_Flag` → **Add base (pedestal) under this flag**.
* Copia el pedestal del color de la bandera desde `mp_b_anderguater` (con su colisión de piso), lo apoya en el piso que hay bajo la bandera y sube la bandera encima, igual que en ese mapa. No se duplica si ya tiene base.
* Si después movés la bandera, la base no la sigue: borrá la base (Map Mesh, textura `bandera y pedestal`) y volvé a ponerla.
* **Ángulo**: el pedestal de `mp_b_anderguater` está girado 45°; ahora sale **derecho** (lados a lo largo de los ejes del mapa = alineado con el barco). En los campos de la bandera: **base angle (deg)** + **Re-place base here** saca la base que tenga (malla **y** su piso del `.hm`) y la vuelve a poner con ese ángulo en la posición actual de la bandera — usalo también después de mover la bandera. Mover o girar la malla de la base con las herramientas normales **no** mueve su piso del `.hm`: usá este botón.
* **Nivelado**: los pedestales de `mp_b_anderguater` están un poco inclinados (1–1,5°, apoyan en suelo con pendiente); la copia se endereza (la base y su piso del `.hm`) antes de girarla al ángulo pedido.
* El mástil inclinado es el diseño del modelo de la bandera (`bandera_roja.NFO` / `bandera_amarilla.NFO`), igual en todos los mapas.

## 38. Barandas en las pasarelas (que nadie se caiga al agua)
Que la bandera vuelva sola a su base cuando cae al agua es lógica de la **DLL del modo** (`mp_CaptureTheFlag.dll` / `mp_CaptureLoveboat.dll`), no del mapa: el editor no puede agregarlo sin reprogramar esa DLL. Lo que sí puede hacer el mapa es evitar la caída: **opcional** (casilla *handrails on the gangplanks*, apagada por defecto) cada pasarela (rampa – tramo plano – rampa) lleva **barandas a los dos lados**, 110 de alto: un pasamanos de tablones visible + paredes de colisión (cajas del `.opt` y paredes del `.hm`). Se ponen o se sacan con *Make twin ships* o **Rebuild gangplanks** según la casilla, y guardar (ya no borra las cajas de colisión de las cajas de carga que estén cerca).

## 39. DLL del modo a elección
*Game mode / sky / spawns / music* → **Choose mode DLL...**: elegís cualquier `.dll` (por ejemplo `mp_CaptureLoveboat.dll`) y la escena la usa como módulo principal; **Standard DLL of this mode** vuelve a la estándar. Solo se guarda el nombre: la DLL tiene que estar en la carpeta del juego con las demás.
Análisis de las dos DLL de capturar la bandera: `mp_CaptureLoveboat.dll` y `mp_CaptureTheFlag.dll` son **idénticas salvo 8 bytes**: la del Love Boat carga `mp_meneo.dll` (el balanceo de cámara del barco) en lugar de `mp_Camera.dll`. La DLL de escena solo maneja marcador, avisos (`__FlagCapture__`, `__FlagRedAlarm__`, `__FlagYellowAlarm__`), sonidos y la lluvia; qué pasa con una bandera soltada (volver a la base, etc.) no está en ella: está en el módulo de la bandera (`mp_Flag.dll`) y/o en el jugador (`mp_player.dll`).

## 40. La bandera vuelve sola a su base
Análisis de `mp_Flag.dll` (clase `Flag`): en `Flag::Run`, en el **servidor**, cuando la vida del que lleva la bandera llega a 0 la bandera se suelta donde está (`LoseFlag`, que anota la hora). Después, mientras nadie la lleve y no esté en su base, si pasó más de **25000 ms (25 s)** vuelve a la base y avisa por chat. Ese tiempo es una sola constante.
*Game mode / sky / spawns / music* → **dropped flag returns after (s)** + **Make flag DLL for this map**: escribe en la carpeta `export` una copia `mp_Flag@<mapa>.dll` con ese tiempo (0 = vuelve en cuanto muere el que la lleva) y hace que las banderas de **este** mapa la usen. Cambian solo 3 bytes; `mp_Flag.dll` no se toca y los demás mapas siguen igual. **Stock mp_Flag.dll** vuelve a la original. El zip de *Export map* la incluye en `dll/`.
Hay que copiar `mp_Flag@<mapa>.dll` a la carpeta del juego (junto a `mp_Flag.dll`) en el servidor y en la PC de cada jugador. En el editor, un módulo `tipo@algo.dll` sigue contando como `tipo` (se ve y se edita igual).

## 41. Reemplazar una textura con una imagen
Ventana *Scene Textures* → elegí una textura → **Replace from image...**: buscás en la PC un PNG / JPG / BMP / TGA y se convierte directo a `.tex` con el **mismo formato** que la original (DXT1 o DXT5, misma cantidad de mipmaps) y, con *keep the original size* (por defecto), el mismo tamaño. La original se guarda una vez como `.tex.bak`; **Restore original** la vuelve a poner. **Por defecto solo para este mapa**: la imagen se guarda como textura nueva `<mapa>__<textura>.tex` y solo las mallas/decals de este mapa pasan a usarla; la original y los demás mapas no cambian. **Back to the original texture** vuelve a la original. La casilla *change it for ALL maps* sobrescribe el archivo original (con `.tex.bak` y *Restore original*).

## 42. Cada mapa con su propio .opt y .hm
Al guardar el mapa (*Save scene* con cambios en el mapa, *Save scene as*, *Rename map*), el editor **nunca** sobrescribe un `.opt` / `.hm` que usa otra escena: si el mapa usa un archivo compartido (las escenas del Love Boat comparten `mp_dm_loveboat.opt` / `.hm`) o con otro nombre, escribe `<mapa>.opt` y `<mapa>.hm` (o `<mapa>_2...` si ese nombre ya lo usa otra escena) y la escena pasa a apuntar a ellos. Solo se guarda encima un archivo que se llama como el mapa y que ninguna otra escena usa.
**Arreglar archivos compartidos ya modificados**: DEBUG → **Map file backups (.bak)** lista los `.opt` / `.hm` que tienen copia original (`.bak`, la que el editor hizo la primera vez que los sobrescribió) y qué escenas los usan; **Restore** la vuelve a poner. Después, tu mapa nuevo tiene que tener sus propios archivos: cargalo y guardalo de nuevo (o *Rename map*).

## 43. Vista previa: siempre se reemplaza
*Save preview* siempre escribe `texs/<mapa>-tbn.tex`; si el mapa ya tenía una, la anterior queda como `<mapa>-tbn.tex.bak` (solo la última anterior).
**Crash al capturar la vista previa (`glBindTexture` error 1282)**: al capturar se borraba la imagen anterior de la vista previa mientras el panel todavía la mostraba en ese mismo cuadro. Ahora las texturas que se reemplazan (vista previa, *Replace from image*, recarga de texturas) se liberan recién al final del cuadro, y un error de dibujo de un panel ya no cierra el editor.

## 44. Cajitas de los botiquines y del módulo elegido
Los botiquines (`mp_salud`) muestran siempre una cajita **verde** (casilla *Show health packs*), además del modelo, y se pueden elegir con clic sobre ella. El módulo seleccionado (spawn, botiquín, bandera, sonido, cámara) muestra su cajita en **amarillo brillante**, visible a través de las paredes, para saber cuál estás editando.

## 45. Herramientas del mapa (ventana *Map tools*)
Ventana **Map tools** (View → *Map tools window*). Cada sección se abre con un clic. La lógica está en `vtoy/app/state_tools.py` y los paneles en `vtoy/app/editor_tools.py`.

**Para no romper el juego**
* **Map check** — *Check the map* lista errores (rojo) y avisos (amarillo) con **Go to**: spawns / banderas / botiquines sin piso debajo (se caen) o flotando, objetos fuera del área de sectores, nombres repetidos, falta la cámara inicial, equipos sin spawns, banderas ≠ 2 en capturar la bandera, archivos que faltan (mapa / piso / modelo = error; textura / animación = aviso), DLL que no son del juego. Se corre solo en cada guardado y avisa en el log. Por consola: `python tools/vtoy_cli.py check-map <carpeta> <escena.scn>`.
* **Show floor collision (.hm)** (también en View): dibuja el piso del juego — **verde = piso, amarillo = rampa, rojo = pared**.
* **Play in the game** — elegís el `.exe` del juego una vez (se recuerda) y *Save, pack the VPK and play* guarda, rehace `demo.vpk` y lo abre. El mapa se elige en el menú del juego (no se conoce un parámetro para abrirlo directo; hay un campo de argumentos por si lo tiene).

**Para editar más rápido**
* **Grupo**: con la herramienta *Select*, **Ctrl+clic** agrega / quita objetos y **Mayús+arrastrar** hace un rectángulo (módulos y props, no los bloqueados). El grupo se ve en celeste. Mover uno con *Move* mueve todos; también *Move group by offset*, *Lock / Unlock / Delete*. Con *move their collision too* las cajas de colisión de los props / mallas van con ellos.
* **Ajuste**: *grid step* redondea X/Z al mover; *stand on the floor (.hm) when moved* apoya el objeto en el piso (los spawns quedan 18 por encima, como en los mapas originales); *Snap selection now* lo aplica a lo seleccionado.
* **Copias**: *Mirror copy* copia al otro lado del plano X = valor (o Z), girado en espejo y, si querés, cambiado de equipo (equipo 0 ↔ 1, ROJO ↔ AMARILLO, bandera roja ↔ amarilla). *Row of copies* hace N copias con un paso.
* **Measure** (herramienta 7): clic en dos puntos → distancia en unidades y metros, sobre el piso, diferencia de altura y dx/dy/dz.

**Para el diseño**
* **Collision editing** (herramienta 8): clic en una caja de colisión → mover / cambiar tamaño / borrar; *Add box here*, *Box around selection*. Piso del `.hm`: *Add floor here*; con dos puntos medidos, *Invisible wall A-B* (caja + paredes del `.hm`) y *Ramp A-B* (cara inclinada); *Floor faces near here* lista las caras cercanas para borrarlas. Todo con deshacer.
* **Map plan**: *Update plan* saca una vista desde arriba del área de juego y marca spawns por equipo, banderas, botiquines y cámara; clic en el plano lleva la cámara ahí.
* **Pieces**: *Save selection as a piece* guarda el grupo (módulos, mallas — los props se guardan como mallas —, sus cajas de colisión y caras de piso) en `prefabs/<nombre>.vtpf` junto al editor; *Place here* la pone en cualquier mapa, girada si querés. Los archivos de pieza solo pueden contener datos del editor (no ejecutan código).

**Para compartir y mantener**
* **Export this map as .zip** sigue igual (escena, `.opt`, `.hm`, texturas, modelos, animaciones, miniatura, DLL, música) y trae `vtoy_manifest.json`.
* **Install a map from .zip...** (también File → *Install map from zip...*, o `vtoy_cli.py install-map`): copia cada cosa a su lugar; **nunca reemplaza** un archivo que el juego ya tiene (si es distinto lo saltea y lo dice). Anota lo que escribió en `vtoy_installed/` y **Uninstall** borra exactamente eso. Después, *Repackage VPK*.
* **History**: cada guardado deja una copia de escena / `.opt` / `.hm` en `vtoy_history/<mapa>/` (los archivos iguales se guardan una sola vez; quedan las últimas 10). **Restore** vuelve a esa versión (la actual se guarda antes); **Compare** lista qué cambió: módulos agregados / quitados / movidos, DLL, mapa, cielo, música, cantidad de mallas / props / cajas, texturas y caras de piso.

## 46. Vista previa del modelo al elegirlo en un módulo
En los campos de un módulo, la lista **models** ahora muestra el modelo sobre el que pasás el mouse **delante de la cámara**, igual que la ventana *Models (.nfo)* (antes lo cambiaba en el propio módulo y rehacía toda la escena en cada movimiento del mouse). Clic = usar ese modelo; cerrar la lista sin elegir deja el que tenía.

## 47. Crear sólidos (dibujo + colisión juntos)
*Map tools* → **Create solid (with collision)** (`vtoy/solids.py`). Elegís forma, medidas, giro y textura, y un clic pone lo que se ve **y** lo que choca:

| Forma | Qué es | Colisión |
|---|---|---|
| **Plank** (tabla) | losa para caminar encima | caja + piso arriba + 4 paredes |
| **Block** | caja, pilar, plataforma | caja + piso arriba + 4 paredes |
| **Wall** | pared fina y alta | caja + paredes |
| **Ramp** | cuña que sube de un extremo al otro | cara inclinada + fondo + laterales (en el `.hm`, como las escaleras del juego; sin caja) |
| **Handrail** | pasamanos con postes | pared del largo y alto de la baranda (no se puede pisar ni cruzar) |

* **Create here**: en el último punto medido, o donde mira el centro de la vista (el punto es el centro de la base).
* **Create between A-B**: entre los dos puntos de *Measure*; el largo y la dirección salen de ahí. La tabla queda con su cara de arriba a la altura de los puntos; la rampa sube del punto bajo al alto (su altura es la diferencia); pared y baranda se apoyan en ellos.
* La textura es cualquiera del juego (por defecto `tablones.tex`; *Use the Fill texture* toma la que elegiste con Mayús+clic en *Fill*).
* **Delete selection with all its collision**: borra la malla elegida con sus cajas y sus caras de piso / pared. Todo se deshace con Ctrl+Z, y un sólido se puede guardar como **pieza**.
* Las cajas de colisión solo se giran sobre el eje vertical (como en todos los mapas del juego). Las caras del `.hm` nuevas (también las de paredes invisibles y barandas de las pasarelas) siguen ahora el mismo sentido de giro que las del juego.

## 48. Carpeta de "Torrente, el juego" (librería sin duplicados)
**File → Torrente, el juego folder...** (o *Browse* en DEBUG → *Library: Torrente, el juego*). Elegís la carpeta donde está **instalado** el juego viejo (o sus datos ya desempaquetados): si solo hay `.vpk`, se desempaquetan una vez en `tj_unpacked/` junto al editor. La carpeta se recuerda y se carga sola al abrir.

La lista tiene cinco tipos: **models (.nfo)**, **maps (.opt + .hm)**, **old scenes**, **textures** y **music**. Con la casilla **only what my game does not have** (activada) solo aparece lo que tu Torrente Online **no tiene con ese nombre de archivo**, así no se duplica nada; abajo dice cuántos se muestran del total. Importar nunca reemplaza un archivo del juego (una textura distinta con el mismo nombre entra con prefijo; una música con el mismo nombre no se copia).

**Vista previa**: en *models*, al pasar el mouse por un nombre el modelo aparece delante de la cámara **con sus propias texturas**, sin importar nada todavía (el seleccionado queda a la vista).

## 49. Barandillas de barco en las pasarelas
Las barandas opcionales de las pasarelas (*Twin ships → handrails*) ahora son como las del barco: panel de barrotes metálicos (`barandillas_poli.tex`, la misma textura y proporción que la baranda original) + pasamanos de madera arriba. En un mapa ya hecho: marcá *handrails* y tocá **Rebuild gangplanks**. En *Create solid* hay una forma nueva, **Ship railing**, para ponerlas donde quieras (con su pared de colisión). Si el juego no tiene esa textura se dibujan postes de madera.

## 50. Colisión automática desde las mallas (`.hm`)
*Map tools* → **Collision from meshes (.hm)** (`vtoy/autohm.py`). El `.hm` original del juego es exactamente eso: los triángulos de las mallas, mirando para el lado visible (comprobado: 1658 caras del `.hm` del Love Boat son triángulos de sus mallas, con la misma orientación). La herramienta hace lo mismo con lo que selecciones (malla, prop o grupo) o con **todo el mapa**:
* *floors and ramps / walls / ceilings*: qué caras generar. *join triangle pairs into quads*: menos caras. *replace the faces already there*: borra antes las caras que ya había dentro del objeto (se puede repetir sin apilar). *thin two-sided floors*: tablas finas de dos caras siempre caminables. *one collision box around each object*: además una caja.
* **Rebuild the whole height map** (hay que tildar la confirmación): rehace todo el piso desde las mallas; lo agregado a mano se pierde. Los modelos que son módulos (.nfo) no entran: siguen con sus cajas de colisión.
* Un mapa sin `.hm` recibe uno nuevo (`<mapa>.hm`) al guardar. Por consola: `vtoy_cli.py auto-hm <carpeta> <escena.scn>`.

## 51. Importar modelos propios (OBJ)
*Map tools* → **Import model (OBJ)** (`vtoy/objimport.py`). Lee `.obj` + `.mtl` (polígonos, índices negativos, sin normales o sin UV), lo pasa al sistema del motor (escala — 100 = archivo en metros —, espejo en Z, V invertida, *Y up* o *Z up*) y lo agrega como **malla del mapa** donde mirás, con un submesh por material. Las imágenes del `.mtl` (PNG/JPG/BMP/TGA) se convierten a `.tex` **nuevos** (lados potencia de 2, DXT1 o DXT5 si tiene transparencia, con mipmaps); un material sin imagen recibe una textura de su color. Nunca se pisa una textura existente: si el nombre está ocupado se usa `<modelo>_<nombre>`. Con *make its collision* se genera su piso / paredes con la herramienta del punto 50. Límite: 200000 triángulos. Por consola: `vtoy_cli.py import-obj <carpeta> <escena> <archivo.obj> x y z [--scale 100] [--up z]`.

## 52. Pintar caras (cambiar la textura por cara)
Herramienta **9 Paint faces** + *Map tools* → **Paint faces** (`vtoy/facepaint.py`). Elegís textura (escribiendo, con *Use the Fill texture*, o **Mayús+clic** en una cara para tomar la suya) y qué pintar: **un triángulo**, **la zona plana alrededor** (una pared, un piso) o **todo ese material de la malla**. Los triángulos pasan a un submesh nuevo con una copia del material; las coordenadas de textura se mantienen salvo que pongas *re-map* (proyección plana cada N unidades). No cambia el archivo de textura ni otros mapas. Los props comparten malla: se pintan todas sus copias (lo avisa). Mallas con candado no se pintan.

## 53. Luces: vista iluminada
*Map tools* → **Lights (lit view)**. **Importante (corrige lo dicho antes):** el motor **no hornea** la luz en las mallas; ilumina en tiempo real por vértice con las luces del `.opt` (ambiente, direccionales y puntuales con distancia *start/end*) más las texturas `glow_*`. Por eso un barco copiado o una pasarela nueva **no pierden nada**: se iluminan igual que el original donde llegue una luz (y al copiar el barco se copian sus luces).
* **Lit view**: dibuja el mapa con esas luces (las 32 más cercanas a la cámara; la caída entre *start* y *end* es aproximada). **Show the reach of the point lights**: esferas de alcance (color = luz, blanco = brillo completo).
* **Add a point light at the camera** con color y distancias; el resto se edita en DEBUG → *Lights*. El motor no tiene sombras proyectadas.

## 54. Sonidos y partículas
*Map tools* → **Sounds and particles** (`vtoy/particles.py`).
* **Sonidos**: el sonido seleccionado muestra su alcance como esfera (celeste = se oye hasta ahí, blanco = volumen completo adentro); *Show the reach of every sound* muestra todos.
* **Partículas**: el formato de `CParticleSystem` está decodificado (155 emisores del juego se leen y escriben idénticos): textura, velocidad, dispersión, radio, partículas/s, vida, empuje, freno del aire, color y opacidad al nacer / al final, tamaños, sonido. Se editan en DEBUG → *Modules*. *Preview particles* las anima en la vista (el emisor seleccionado siempre); **Add particle emitter here** con presets sacados del juego: humo del barco, humo de fuego, fuente, burbujas, humo de color. El juego **no tiene chispas**: hay un preset *sparks (experimental)* armado a partir de la fuente, a probar en el juego.
* *Preview rain*: rayas de lluvia alrededor de la cámara. La vista previa es aproximada (el mezclado exacto es del juego).

## 55. Prueba de recorrido
*Map tools* → **Walk test** (`vtoy/walk.py`). *Walk from where the camera is* o desde un punto de inicio: **WASD** camina, **Espacio** salta, **Mayús** corre, botón derecho mira, **Esc** termina. El cuerpo choca con lo mismo que el jugador: piso, rampas y paredes del `.hm` y las cajas de colisión del `.opt`, tal como están en ese momento (guardados o no). Si se cae del mapa lo avisa en el log, lo devuelve al último piso y deja un *Go to* al lugar. Velocidad, escalón y salto son estimaciones razonables (no salen del juego): sirve para encontrar agujeros, pisos que faltan y pasos bloqueados.

## 56. Balance de equipos
*Map tools* → **Team balance** (`vtoy/navgrid.py`). *Measure the map* recorre el piso caminable (una grilla por nivel, sin atravesar paredes ni cajas, subiendo escalones y rampas, bajando caídas de hasta 4 m) y calcula por equipo: distancia y tiempo **a la bandera enemiga** (mínimo, promedio, máximo desde sus puntos de inicio), **bandera de vuelta a casa**, a su propia bandera y **al botiquín más cercano**; avisa de spawns sin piso o desde los que no se llega. El veredicto compara el ataque completo (ir + volver): *balanced* (< 3 %), *slight advantage*, *clear advantage*. Las rutas se dibujan en la vista y en el *Map plan*. Los mapas originales dan 0,0–0,6 % de diferencia. Por consola: `vtoy_cli.py balance <carpeta> <escena.scn>`.

## 57. Botiquines: `unk_string1`, `unk_string2` y tiempo de reaparición
En los 665 botiquines de todos los mapas del juego esos dos textos están **vacíos**; son los dos textos comunes a los módulos con modelo (nombre de animación `.KEY` y uno sin uso). Ahora aparecen con ese nombre. El dato propio del botiquín es **health** (0 = 50). **No hay tiempo de reaparición en el mapa**: lo decide `mp_salud.dll`. Para cambiarlo haría falta ese DLL y hacer una copia parcheada, como con la bandera (punto 40).

## 58. Armas permitidas por mapa
DEBUG → *Game mode / sky / spawns / music* → **Weapons allowed on this map**. Cada jugador lleva un arma por **grupo** (teclas 1–5): 1 cuchillo · 2 pistola · 3 uzi / escopeta / rifle / cetme · 4 pesadas (bazooka, lanzagranadas, metralleta, lanzallamas, bengalas) · 5 minas. Destildás los grupos que no querés y **Make weapons DLL for this map** escribe una copia del DLL de modo del mapa (`<DLL>_<mapa>.dll`, en la carpeta de exportación y dentro del zip del mapa) que no entrega esos grupos; la escena pasa a usarla. El DLL del juego no se toca.

Cómo funciona (visto en `mp_CaptureTheFlag.dll` / `mp_CaptureLoveboat.dll` y `mp_player.dll`): el DLL de modo reparte las cinco armas en dos lugares — al crear al jugador (`NewWeapon`) y en cada reaparición (`ClearWeapons` + `ActiveWeapon`) — y "tener" un arma es una marca por arma que pone esa llamada. La copia cambia la llamada del grupo por dos `pop` (mismo tamaño, se puede volver atrás con *All weapons again*). Sin el grupo 3 el jugador nace con la pistola en la mano; el cuchillo no se puede quitar.

* Si el mapa tiene **armas en el suelo** (`mp_generador`) de un grupo desactivado, el panel lo avisa y **Remove those pickups** las quita (el Love Boat no tiene ninguna).
* Otros modos (deathmatch, etc.): funciona si su DLL reparte las armas igual; si no, lo dice ("unknown mode DLL") y no escribe nada.
* Como el DLL de la bandera: la copia tiene que estar en la carpeta del juego del servidor y de cada jugador. **No probado en el juego.**

## 59. Opciones de vista guardadas
Todo lo de *View options*, el menú View y las casillas mostrar / ocultar (más el campo de visión) se guarda en `vtoy_editor.json` y vuelve al abrir el editor.

## 60. Autos (`mp_CCar`) indestructibles
`mp_CCar` es el módulo del auto que explota; en la escena no tiene ningún dato de "vida" (lo decide su DLL). En los campos del módulo: **Make it indestructible (scenery + collision box)** lo convierte en `RenderNFO` (el mismo modelo, solo dibujado: nada lo puede romper) y agrega una caja de colisión de su tamaño y giro para que siga frenando jugadores y balas. **All the cars of the map** lo hace con todos (menos los que tengan candado). Se deshace con Ctrl+Z. Para dejarlo como auto "de verdad" pero con más vida haría falta `mp_CCar.dll`.

## 61. Pasarelas una por una (agregar, mover, ensanchar, quitar)
DEBUG → *Twin ships* → **Gangplanks: add, move, remove**. Las pasarelas se reconocen en el propio mapa (no se guardan aparte), así que la lista funciona en mapas ya hechos.
* Cada pasarela: **posición a lo largo de los barcos** (negativo = proa), **ancho**, **barandillas**, *Go to* y *Remove*. **Apply the changes** las rehace: las tablas, las rampas, las barandillas, las cajas de colisión y el piso (`.hm`) se mueven o se quitan juntos; el resto del mapa no se toca.
* **New gangplank**: *Wide one at the bow* propone la cuarta — posición −4800, **640 de ancho (el doble)**, con barandillas — en la zona de la proa donde los cascos se afinan; *Where the camera is* usa la posición de la cámara. La pasarela mide sola el borde de cada cubierta en ese lugar (ahí queda de ~28 m de largo en vez de ~10) y pasa por encima de las barandas con una rampa de cada lado.
* No deja superponer dos pasarelas ni ponerlas donde no hay cubierta. *Rebuild gangplanks* y *Rebuild floor collision* ahora respetan las pasarelas que tenga el mapa.

## 62. Exportar el mapa con todas sus dependencias
*File → Export map…* ahora mete en el zip **todo** lo que la escena nombra:
* escena, `.opt`, `.hm`, miniatura, cielo, todas las texturas de las mallas y decals;
* cada modelo (`.nfo`) de cada módulo — también los de módulos que el editor no desarma — con sus texturas;
* **animaciones (`.key`)**: antes no entraba ninguna (el nombre viene relativo a `keys/`, p. ej. `varios\puerta_open.KEY`, y se buscaba mal). Ahora van todas las que nombra cada módulo (puertas y botones tienen dos) y además las que el juego carga por el nombre del modelo (`<modelo>.KEY`, `Reposo_<modelo>.KEY`…);
* texturas de las partículas, **sonidos** (`wavs/` de las fuentes de sonido), **música** y los DLL propios del mapa (modo, bandera, armas).

El log dice cuántos archivos fueron de cada tipo y lista los que el mapa nombra pero **no se encontraron** (así se ve si falta algo). *Install map from zip* también coloca `wavs/` en la carpeta de sonidos del juego, sin reemplazar nada.

## 63. Ocultar objetos en el editor (el ojito)
Al lado de cada candado hay un **ojo**: en la lista de módulos, en *Map Mesh* (mallas y props) y en el panel del objeto seleccionado. Clic = ese objeto **deja de dibujarse en el editor** (ojo gris tachado) para que no tape lo que estás editando; clic otra vez = vuelve.
* El objeto **sigue en el mapa**: se guarda, se exporta, choca y lo cuentan todas las herramientas (colisión, prueba de recorrido, balance, *Map check*). Solo no se ve, y por eso tampoco se puede cliquear en la vista (sí desde la lista).
* **H** oculta lo seleccionado (y el grupo); **Mayús+H** o *Show all* muestra todo. También en el menú View. Arriba de las listas dice cuántos hay ocultos.
* Se recuerda por mapa en `vtoy_editor.json`, igual que los candados. Ojo: las capturas y la miniatura del mapa salen como se ve, sin lo oculto.

## 64. Escuchar los sonidos del mapa
* En los campos de cualquier módulo que nombre un sonido aparece una fila **Play / Stop** por cada `.wav`: las fuentes de sonido (`mp_SoundSource`), las puertas y botones (traen su propio sonido), módulos sin decodificar, y los emisores de partículas (suena la fuente de sonido a la que apuntan).
* En `mp_SoundSource` hay además una lista **sound of the game** con todos los sonidos disponibles: elegir uno lo pone en el módulo y lo reproduce.
* *Map tools → Sounds and particles → Emitters and sounds of this map*: cada sonido de la lista tiene su **Play**.
* Suena una vez; con **loop** se repite hasta tocar *Stop*. Usa el mismo reproductor que la música (en Windows los `.wav` se reproducen sin instalar nada). Si el archivo no está, dice en qué carpetas lo buscó (`wavs` junto a `demo.vpk` y dentro de los datos desempaquetados).
* Es para oír qué sonido es: no simula la distancia ni el volumen del juego (eso lo muestran las esferas de alcance).

## 65. Luces y decals: seleccionar, mover, ir, duplicar, borrar
En DEBUG → *Lights* y *Decals*, cada luz / decal tiene ahora los mismos cinco botones que los módulos: **Select**, **Move here** (lo trae a donde está la cámara), **Go to**, **Duplicate** (copia al lado, queda seleccionada) y **Delete** (la X sigue estando).
* **Seleccionados** se comportan como cualquier objeto: herramienta *Move*, **G** para arrastrar, **Q** copia, **Supr** borra, Ctrl+Z deshace. En la vista se marcan con una cajita amarilla; la luz puntual seleccionada muestra además su alcance (esfera *end* y *start*). El panel del objeto seleccionado muestra sus campos.
* **Show the lights in the view** / **Show the decals as boxes in the view**: dibuja una cajita por luz (amarillo claro) o decal (rosa) y permite **seleccionarlos con clic** en la vista. Apagado por defecto (hay mapas con más de 300 luces).
* No tienen candado ni ojito.

## 66. DLL del mapa al exportar, candado/ojo en luces y decals, luces gemelas, distancia de dibujado
* **DLL al exportar**: el DLL de modo (y el de la bandera) se busca ahora en: la copia que hizo o cargó el editor, la carpeta de exportación, junto a `demo.vpk` y **`comun\bin\release`** (o `bin\release`) de la instalación, subiendo desde la carpeta de datos, sin importar mayúsculas. Si no aparece, el aviso lista las carpetas donde buscó.
* **Borrar una luz cerraba el editor**: arreglado (pasaba al borrar cualquier luz que no fuera la primera de la lista).
* **Candado y ojo en luces y decals**: en las listas y en el panel del seleccionado. Con candado no se pueden cliquear, mover ni borrar; ocultos no se dibujan (y la luz oculta no ilumina la *Lit view*). Siguen en el mapa.
* **Twin ships → Lights: the same on both ships**: copia las luces puntuales del barco A (amarillo) al B (rojo), reemplazando las que tuviera. Con *mirrored* cada luz queda del lado opuesto de su barco, así los dos se iluminan como un reflejo respecto del agua que los separa. Si el sol / la luz ambiente estaban guardados dos veces, deja uno.
* **Distancia de dibujado** (DEBUG → escena, junto a *Camera far plane*): el juego no dibuja nada — mapa, modelos, jugadores — más allá del **plano lejano de la cámara** de la escena. El Love Boat trae 11000 y los barcos gemelos miden más. **See the whole map** lo sube a lo que mide el mapa de punta a punta (y corre la niebla si quedaba antes). **Full detail at any distance** quita las versiones simplificadas de las mallas que cambian con la distancia (algunas terminan en un solo triángulo).

## 67. Sombreado tipo mp_b_garaje, restaurar detalle, piezas de otros mapas, menos cierres
* **Capa de sombreado** (*Map tools → Shading layer*): lo que hace que mp_b_garaje y otros no se vean planos **no es la niebla ni las luces**: sus mallas tienen una **segunda textura multiplicada** encima de la normal (`glow_galo.tex`: centro blanco, borde oscuro), con un segundo juego de coordenadas que es una proyección plana repetida cada ~6–7 m (medido en mp_b_garaje). Bajo cada "mancha" la textura queda con su color; entre manchas se oscurece. Las manchas de color (`glow_galo_amar`, `_azul`) además tiñen.
  * Elegís la textura de mancha, cada cuántas unidades se repite, y se la das a la selección (un prop cambia su malla: todas sus copias) o a todo el mapa. Las manchas quedan centradas en la cámara. *Remove it* la saca.
  * **Make my own spot texture**: crea una `glow_<nombre>.tex` nueva con brillo en el centro, en el borde y tinte. Centro más oscuro que el borde = una **sombra** en el medio (debajo de un objeto, por ejemplo, con la mancha centrada ahí y del tamaño del objeto).
  * **El editor no dibuja esta capa**: se ve en el juego. No probado en el juego.
* **Restore detail at a distance** (debajo de *Full detail at any distance*): vuelve a poner las versiones simplificadas de las mallas. Desde esta versión, *Full detail* guarda lo que saca (carpeta `lods/` junto al editor) y *Restore* lo devuelve exacto. Para mapas a los que ya se les había sacado antes, las busca en los mapas originales del juego por la forma de cada malla (un barco copiado encuentra su original y las versiones lejanas se mueven con él).
* **Piezas de otros mapas** (*Map tools → Pieces of other maps*): elegís un mapa del juego, filtrás por textura (p. ej. `crist`), pasás el mouse por una pieza y aparece frente a la cámara; *Bring it here* la agrega al mapa actual como malla nueva, con su colisión opcional. El juego junta muchas cosas separadas en una sola malla: **Split it in its separate parts** las separa y podés traer solo una. Las texturas son las del juego (compartidas): no se copia nada; el mapa de origen no se toca. (En mis datos el comercial es `mp_dm_comercial.opt`; `mp_dmt_comercial` usa ese mismo mapa.)
* **Cierres del editor**: el que pasaba al borrar luces venía de comparar objetos del mapa entre sí (Python comparaba sus números de a uno y fallaba); ahora todos los objetos del mapa y de la escena se comparan por identidad, que era lo que el editor necesitaba. Además: un error en cualquier panel o en la vista 3D ya no cierra el editor (queda en el log una vez), Dear ImGui repara lo que un panel dejó abierto, girar / escalar fuentes de sonido y partículas (que solo tienen posición) ya no se intenta, y copiar algo que ya no está en la escena da un aviso en lugar de fallar. Probé cada tipo de objeto con cada herramienta (mover, girar, escalar, copiar, borrar, deshacer) en un test automático.

## 68. Lock all en luces y decals, ver lo que alumbra una luz, colisión según la forma de la malla
* **Lock all / Unlock all** en DEBUG → *Lights* y *Decals*: bloquea o desbloquea todas de una vez (después no se pueden cliquear, mover ni borrar).
* **Ver lo que alumbra una luz** (en la luz seleccionada o abierta en la lista):
  * Un texto dice qué hace: la **ambiental** alumbra todas las caras del mapa igual, desde todos lados, esté donde esté (por eso su cubo no dice nada: su posición no importa) y marca lo más oscuro que puede quedar un lugar; la **direccional** es un sol: alumbra todo el mapa desde un lado sin límite de distancia, con el ángulo desde arriba / abajo y qué porcentaje de las superficies del mapa la miran.
  * **See only this light in the lit view**: la *Lit view* se prende y muestra **solo esa luz**: lo que queda negro es lo que no alumbra. *Light with every light again* (en *Map tools → Lights*) vuelve a todas.
  * En la vista: una **grilla de flechas** con la dirección del sol delante de la cámara, **rayos en todas direcciones** para la ambiental, el **cono** de un foco y el alcance de una puntual. Se apaga con *Show where the selected light shines*.
* **Colisión según la forma de la malla** (*Map tools → Collision from meshes*, al final): en vez de una caja tan grande como todo el objeto, una **caja fina por cada lado plano** (barandillas, vallas, carteles — aunque doblen esquinas o estén lejos entre sí dentro de la misma malla, como hace el juego al juntarlas por textura) y una caja ajustada, girada como la pieza, por cada pieza sólida. Grosor de los lados planos y altura mínima configurables.
  * *Boxes from the mesh shape (selection)* para lo seleccionado.
  * Con **texture contains** (p. ej. `barandilla`): solo los triángulos con esa textura. *Select the ones without collision* selecciona los objetos que no tienen (menos de la mitad de su superficie dentro de una caja o junto a una pared del .hm); *Boxes from the mesh shape for all of them* se las pone a todos en el mapa (con *only the ones without collision*, deja igual los que ya tienen). Bloqueados y ocultos no se tocan. Ctrl+Z deshace.
* **mp_dm_carretera**: de las 20 piezas con textura de barandilla, 4 no tenían colisión (las tres largas de la ruta — mallas 102, 138 y 139, de hasta 27 m — y la 99, cubierta a medias). Recibieron 15 cajas finas que siguen cada tramo. Las otras 16 ya tenían (cajas o paredes del .hm), incluidas las bajitas de la terraza. No probado en el juego.
* **Crear sólido → Crear entre A-B**: ahora los puntos se eligen desde el mismo panel. *Marcar A y B en la vista* activa la herramienta Measure (7): el primer clic en la vista pone A y el segundo pone B. Otra opción es *A = acá* / *B = acá*, que toman el punto al que mira el centro de la vista. El panel muestra A y B (o "sin elegir") y el largo entre los dos. Si apretás *Crear entre A-B* sin los dos puntos, se activa Measure y el log explica qué hacer.
* **Medir con valores escritos a mano** (*Map tools → Measure* y *Crear sólido*): A y B ahora son campos X / Y / Z. Se pueden arrastrar, o escribir un número con doble clic (o Ctrl+clic) en el campo. Un punto que todavía no está elegido tiene un botón *Escribir A* / *Escribir B*, que lo pone donde mira la vista para que lo corrijas desde ahí. La distancia y *Crear entre A-B* usan los valores escritos.
* **Cambiar un sólido ya creado, con su colisión** (*Crear sólido*): si seleccionás un sólido hecho con *Crear sólido* (*Crear acá* o *entre A-B*), aparece **Sólido seleccionado** con su posición X/Y/Z (centro de abajo), giro, largo, ancho, alto y textura. Cambiás los valores y apretás **Aplicar (malla + colisión)**: se rehacen juntos lo que se ve, su caja de colisión y sus paredes / piso del .hm (las viejas se borran). Un Ctrl+Z vuelve todo atrás. El editor recuerda cómo hiciste cada sólido de cada mapa, también después de cerrarlo.
  * Las herramientas **Move / Rotate / Scale** mueven solo lo que se ve; la colisión queda donde estaba. Para un sólido, usá estos campos.
  * Los sólidos hechos antes de esta versión no tienen guardado cómo se hicieron: hay que borrarlos con *Borrar selección con toda su colisión* y crearlos de nuevo.
* **Girar cualquier caja de colisión** (*Collision editing*, herramienta 8): además de centro y medio tamaño, ahora tiene **giro (grados)**.
* **Exportar también las DLL de los módulos**: el zip lleva en `dll/` **todas** las DLL que usa la escena: la del modo y la de cada tipo de módulo (`mp_CCar.dll`, `mp_SoundSource.dll`, …), también las originales del juego. Las busca en `comun\bin\release` de la instalación (y en las demás carpetas de antes), sin importar mayúsculas. Las que no encuentra salen en la lista de faltantes. **Instalar mapa desde zip** las copia en la carpeta donde el juego tiene sus DLL (`comun\bin\release` si la encuentra), y nunca reemplaza una que ya exista y sea distinta.
* **Buscar módulos** (DEBUG → *Modules*): un campo **buscar** filtra la lista. Podés escribir un tipo (`mp_door`, `mp_soundsource`) o una palabra del nombre, el modelo, el sonido o la animación (`gaviota`), sin importar mayúsculas. Con varias palabras tienen que estar todas (`gaviota mp_soundsource`). Muestra "N de M módulos" y botones para **seleccionar**, **bloquear / desbloquear** y **ocultar / mostrar** los que aparecen.
* **Guardar como / Renombrar mapa no dejaba**: si la DLL de modo tenía clima (`the comparison string is never referenced`), el error cortaba el guardado **después** de haber escrito el `.opt` nuevo. Ese archivo a medio guardar bloqueaba todos los intentos siguientes ("save as failed: …\mp_x.opt"). Ahora:
  * si no se puede hacer la copia de la DLL para el nombre nuevo, se guarda igual con la DLL que tenía, y un aviso lo dice;
  * si algo falla a mitad de camino, se borra lo que alcanzó a escribir;
  * un `.opt` / `.hm` con el nombre nuevo que **ninguna escena usa** (como el que dejó el error) se aparta como `<nombre>.opt.old` (no se borra) y el guardado sigue;
  * si lo usa otra escena, o ya hay una escena con ese nombre (aunque esté en otra subcarpeta), el mensaje lo dice claro y no se reemplaza nada.
* **Nombrar el .opt / .hm como la escena** (DEBUG, al lado de *Rename map*): aparece cuando la escena usa archivos con otro nombre (p. ej. `mp_dm_laberintomalibu.scn` con `mi_dm_laberintomalibu_t.opt`). Guarda el mapa y la colisión como `mp_dm_laberintomalibu.opt` / `.hm` y la escena pasa a usarlos. Los viejos quedan como estaban. Debajo se ven los nombres de los archivos que usa la escena.
* **Actualizar escenas / Actualizar mapas**: ahora releen todo de verdad, también los mapas y modelos que ya estaban en memoria. Si cambiaste un archivo por fuera del editor, al cargarlo se lee el del disco. En el log dice cuántas escenas y mapas encontró.
* **Icono en la barra de tareas**: no había ningún icono en la carpeta `icon`, y como el editor tiene su propio botón en la barra de tareas de Windows (no agrupado con Python), ese botón salía en blanco. Ahora viene un icono propio (`icon\vtoy.ico` / `vtoy.png`: una V blanca con un + naranja), y si la carpeta queda vacía el editor lo dibuja solo. Para el **.exe**: copiá la carpeta `icon` nueva junto a `VToyEditor.exe` (alcanza para la ventana y la barra de tareas) y volvé a correr `build_exe.bat` para que el archivo .exe también lo tenga. Si lo tenías anclado a la barra, desanclalo y volvé a anclarlo (Windows guarda el icono viejo).
* **Icono en la barra de tareas (2)**: el diálogo de *Choose demo.vpk* se abría antes de que el editor le dijera a Windows quién es. Windows quedaba entonces con la identidad de Python para todo el proceso, y por eso salía la pluma. Ahora la identidad del editor se fija apenas arranca, antes de cualquier ventana. Además los diálogos de archivos (elegir demo.vpk / carpeta, importar, carpeta de *Torrente, el juego*) llevan el icono del editor.
* **Icono con el .exe**: el .exe ya es un programa propio con su icono, así que ahora la identidad aparte para la barra de tareas se usa solo cuando el editor corre desde Python. Así la consola y la ventana del editor quedan en el mismo botón, con el icono. Para tener **solo la ventana del editor, sin consola**: `build_exe_sin_consola.bat` (o `build_exe.bat noconsole`). Los mensajes y errores siguen yendo a `vtoy_editor.log` junto al .exe. En auto-py-to-exe es *Window Based*.
* **Consola y log desde el menú** (*Settings*, arriba):
  * **Mostrar la ventana de consola**: la muestra o la oculta mientras el editor corre. En un .exe compilado sin consola, abre una nueva y los mensajes pasan a salir ahí. A esa consola se le saca la X, porque cerrar la consola cierra el editor; se oculta desde el mismo menú.
  * **Escribir vtoy_editor.log**: prende o apaga el log (si se apaga y se vuelve a prender, sigue el mismo archivo).
  * Las dos opciones se recuerdan (`console` y `log` en `vtoy_editor.json`) y se aplican al abrir el editor. Con el log apagado, un cierre por error no deja rastro: dejalo prendido mientras pruebes cosas.

## 69. Herramientas nuevas (Map tools)
* **Recorrido de varios puntos**: marcás A, B, C… con clic en la vista (*Marcar puntos en la vista*), o con *Agregar punto acá*, y podés corregir cada punto con X/Y/Z. Con *Cerrado*, el último vuelve al primero. Después:
  * **Crear a lo largo del recorrido**: una baranda, pared, tablón, etc. por tramo, cada uno con su colisión y editable después (*Sólido seleccionado*). Todo el recorrido se deshace con un solo Ctrl+Z.
  * **Poner copias a lo largo del recorrido**: copias del objeto seleccionado (prop, modelo o malla) cada N unidades, giradas como el tramo y apoyadas en el piso. Quedan seleccionadas.
* **Pincel de objetos**: seleccionás uno o varios objetos (Ctrl+clic) y apretás *Usar los objetos seleccionados como pincel*. Con *Pintar* activado, cada clic en la vista desparrama N copias en un círculo, al azar entre los del pincel, giradas y de tamaño variable, separadas por lo menos X unidades y apoyadas en el piso. *Desparramar acá* hace lo mismo sin clic. Cada clic se deshace por separado.
* **Bajar al piso / alinear / repartir**: apoya la selección y el grupo en el piso que pisan los jugadores. *Alinear X / Y / Z* les da el valor del primero seleccionado, o el más bajo / más alto. *Misma distancia entre ellos* deja los dos extremos donde están y reparte el resto en línea recta.
* **Buscador de caídas y trampas** (tarda unos segundos, sin congelar el editor): recorre el mapa como un jugador desde cada punto de aparición. En **rojo** marca los bordes sin piso del otro lado (te caés del mapa). En **naranja**, los lugares a los que se puede caer pero de los que no se sale caminando. Cada uno tiene *Ir*. Es una búsqueda aproximada (no conoce los saltos): son lugares para revisar, no errores seguros.
* **Revisión de puntos de aparición**: avisa de los que están dentro de una pared o caja, en el aire o sin piso, y de los que ven en línea recta un punto del otro equipo (a la altura de los ojos; cuentan las paredes, las mallas y las cajas).
* **Mapa de carga**: cuenta los triángulos por cuadrado de 15 m y los pinta en la vista de verde (liviano) a rojo (pesado), con la lista de los más pesados y *Ir*. Los transparentes (hojas, rejas, vidrios) cuentan triple, porque son los que más cuestan. Ojo: el número de triángulos transparentes del log al cargar está inflado, porque el editor los parte en pedazos para ordenarlos; este cuenta los reales.
* **Limpiar colisión**: busca cajas **duplicadas**, cajas **dentro de otra** y cajas **solas** (sin nada del mapa cerca), y las marca en rojo. Las dos primeras se borran con un botón. Las solas se revisan de a una (*Ir* / *Borrar*), porque muchas veces son paredes invisibles a propósito en el borde del mapa.
* **Texturas: buscar / reemplazar**: lista de texturas del mapa por triángulos y objetos (*Usar* la copia al campo), y reemplazo en todo el mapa o solo en la selección. Muestra también las texturas que nombra un material pero que ningún triángulo usa: ahora **no se exportan**.
* **Sectores**: el juego divide el mapa en sectores y dibuja desde cada uno lo que ese sector lista. *Rehacer los sectores* agrega cada malla, prop y caja de colisión a todos los sectores donde está ahora (no saca nada). Úsalo si algo que moviste lejos desaparece desde ciertos lugares en el juego. No probado en el juego.
* **Animaciones (.key): velocidad**: elegís una animación de la escena (o escribís su nombre), la velocidad (2 = el doble de rápido, 0,5 = la mitad) y un nombre. Se crea un `.key` nuevo al lado del viejo (nunca encima), con los cuadros recalculados y los sonidos de la animación corridos con ella. Si hay un módulo seleccionado, puede pasar a usar la nueva. No probado en el juego.
* **Luces direccionales y ambientales "que vuelven a su lugar"**: no es un error del guardado. En el `.opt` del juego un sol (direccional) guarda **solo su dirección** y una luz ambiental **solo sus colores**: no tienen posición, porque alumbran todo el mapa igual. Al guardar no había dónde escribir la posición, así que al volver a cargar aparecían en 0,0,0. Ahora el editor recuerda dónde dejaste sus marcas (`light_marks` en `vtoy_editor.json`) y el panel de la luz lo aclara. Moverlas no cambia nada en el juego; lo que cuenta es la **dirección** (sol) y el **color**.
  * Los mapas del juego tienen hasta **3 soles** y siempre **una sola luz ambiental**. *Revisar el mapa* avisa si hay más de una ambiental (el juego podría no tener en cuenta las demás) o más de 3 soles. Para más luz ambiental, subile el color a la que tenés.
  * Duplicar un sol o una ambiental avisa que su luz se suma a la otra en todo el mapa.

## 70. Luz pareja en los barcos gemelos, clima, recorridos, simulación de partida y más
* **Luz igual en los dos barcos** (*Twin ships → Lights: the same on both ships*): el barco B es una **copia del A corrida en X**, no un espejo. La opción "espejada", que estaba activada por defecto, ponía cada luz del lado opuesto, así que cada parte del barco B quedaba alumbrada distinto que la misma parte del A. Ahora:
  * **Alumbrar los dos barcos igual** copia cada luz de A al **mismo lugar** de B. Los soles y la luz ambiental ya son iguales para los dos.
  * **Comparar cuánta luz tiene cada barco** calcula el brillo promedio de cada barco con todas las luces y las partes alumbradas distinto, con botones *A* / *B* para ir a cada una. En verde si la diferencia es menor al 3 %.
  * La forma espejada sigue en *otras formas*, sin tildar.
* **Clima y cielo**: presets *Día, Atardecer, Noche, Tormenta, Niebla*. Cambian el cielo (si el juego tiene uno que corresponda), el color y la distancia de la niebla y, si querés, la luz ambiental y los soles. Se ve en la vista y se deshace con Ctrl+Z.
* **Animaciones: recorrido**: *Mostrar por dónde van los modelos animados* dibuja en celeste el camino de cada modelo animado (helicóptero, barco…). *Hacer el recorrido nuevo* crea un `.key` nuevo con el recorrido más grande o más chico y/o corrido, y el módulo seleccionado pasa a usarlo. También la copia más rápida/lenta ahora cambia bien el nombre guardado dentro del módulo. No probado en el juego.
* **Simulación de partida, en todos los modos**: cada punto de aparición corre por el camino más corto a donde lo manda el modo:
  * capturar la bandera: a la bandera enemiga y de vuelta;
  * destruir el objetivo: al objetivo;
  * deathmatch por equipos: hacia el otro equipo;
  * deathmatch: a un botiquín y al medio.

  Dibuja los recorridos por color de equipo, marca en blanco dónde y cuándo se cruzan primero (en segundos), y lista los lugares por donde pasan más recorridos.
* **Armado del modo de juego (parejo)**: elegís el modo, marcás Base A y Base B y apretás *Armarlo*. Pone N puntos por equipo en círculo alrededor de cada base mirando a la otra, las banderas en las bases (CTF), el objetivo en el medio (DO) y botiquines de a pares a la misma distancia de cada base (solo si el mapa no tiene). En deathmatch reparte los puntos por todo el piso caminable, lo más separados posible. Los bloqueados no se tocan.
* **Huecos en el piso**: rendijas entre dos pisos del .hm donde se traba un pie o se cae un jugador (en rosa). **Objetos enterrados**: mallas y props que quedan totalmente debajo de todo piso (en violeta), con *Seleccionar* para borrarlos.
* **Cambios desde una versión guardada**: elegís una versión del historial y marca en la vista lo nuevo (verde), lo sacado (rojo) y lo movido (amarillo): mallas, props, cajas de colisión y módulos.
* **OBJ para Blender** (*Import model (OBJ)*, abajo): *Exportar OBJ* saca la selección (o todo el mapa) con sus texturas en PNG y sus cajas de colisión como material `collision`. Al importarlo, esas caras vuelven a ser cajas, y *Importar donde estaba al exportar* lo pone en el lugar de origen. 1 unidad del OBJ = 1 m.
* **Buscador de comandos y atajos**: **Ctrl+P** abre un buscador. Escribís parte del nombre de cualquier herramienta o sección y Enter la abre o la ejecuta (↑/↓ para elegir). En *Atajos* le asignás tu tecla a cualquier comando (Ctrl+1, Shift+F5, Alt+G…); se guarda en `vtoy_editor.json`.
* **Modelos que cambian a uno simple de lejos**: algunos modelos (.nfo) traen dos o más versiones y el juego pasa a la más simple desde cierta distancia. Por ejemplo, `yate_anim.NFO` de *Torrente, el juego* tiene 277 triángulos de cerca y 116 desde 35 m. Si el módulo seleccionado tiene uno de esos, su panel lo muestra en naranja ("más simple desde X m") con el botón **Detalle completo a cualquier distancia (este modelo)**. Ese botón crea `<modelo>_hd.NFO` al lado del original, que no se toca, con las versiones lejanas desactivadas (su distancia pasa a 100 km, la misma que usan los modelos de una sola versión). El módulo y todos los que usan ese modelo pasan a usar la copia, y la exportación la lleva con el mapa. No probado en el juego.
  * `yate_spinelli.NFO` tiene **una sola versión** (779 triángulos): si es ese el que cambia, el botón lo dice. Lo que cambia entonces es otra cosa, por ejemplo una malla del mapa con versiones lejanas (para eso está *Full detail at any distance* del mapa).
* **Recorrido de varios puntos: mover los puntos como con la Pluma**: con *Marcar puntos en la vista* activado:
  * clic en un punto: lo agarrás y lo arrastrás. Se mueve a su misma altura; con **Ctrl** apretado se pega a lo que está bajo el mouse, como una pared o un techo;
  * clic en una línea entre dos puntos: agrega un punto ahí, ya agarrado;
  * clic en otro lado: agrega un punto nuevo, y si mantenés apretado lo podés acomodar antes de soltar;
  * **Alt+clic** en un punto: lo saca.

  El punto agarrado se ve amarillo.
* **Colisión sola a lo largo de los puntos** (para una baranda que ya está pero deja pasar): en *Recorrido de varios puntos* tildá **Solo colisión (invisible, sin textura)**, o dejá la textura vacía, y apretá *Crear a lo largo del recorrido*. Pone cajas de colisión invisibles del ancho y alto elegidos, paradas sobre los puntos y giradas como cada tramo. En los tramos que suben o bajan se cortan cada 2 m para seguir la pendiente, y se solapan un poco en las esquinas para no dejar huecos. No agrega nada visible. Antes, sin textura, el sólido no se creaba y no quedaba colisión.
  * Lo mismo desde **Crear sólido**: *Crear a lo largo de los puntos del recorrido (A, B, C …)* usa los puntos marcados en *Recorrido de varios puntos* con la forma, el ancho y el alto de ese panel. Con la textura vacía hace solo colisión.
* **Medir con más puntos que A y B** (herramienta 7, *Measure*): cada clic agrega un punto (A, B, C, D…), sin límite. Ya no empieza de nuevo al tercer clic: para empezar de nuevo está *Clear*.
  * Clic en un punto: lo arrastrás (a su altura; con Ctrl se pega a lo que está bajo el mouse). Clic en la línea entre dos puntos: agrega un punto en el medio. Alt+clic en un punto: lo saca.
  * En la vista se ve la letra de cada punto y la distancia de cada tramo. En el panel: cada punto con X/Y/Z (y una x para sacarlo), cada tramo con su largo, el largo en el piso y la altura, el **total**, la distancia en línea recta del primero al último y cuánto ocupan todos (ancho × largo × alto).
  * *Escribir C* (o la letra que siga) agrega un punto donde mira la vista. *Usarlos como puntos del recorrido* los pasa a *Recorrido de varios puntos*.
  * Las herramientas que usan A-B (sólido entre A-B, pared invisible, rampa) toman los dos primeros.
* **Autos indestructibles, uno tras otro**: después de *Make it indestructible* el auto pasa a ser un RenderNFO de verdad (antes conservaba su tipo de mp_CCar por dentro) y sigue seleccionado. Con varios autos seleccionados (Ctrl+clic) aparece *Los N autos seleccionados*.

## 71. La colisión acompaña a los objetos, armas una por una, formas, Map tools ordenadas
* **Copiar muchos objetos y moverlos juntos** (Q con un grupo seleccionado): antes se copiaba solo el objeto principal y el grupo que se movía eran los originales. Ahora **se copia todo el grupo** y las copias quedan seleccionadas y siguen al mouse.
* **La colisión va con el objeto** (*Construir → Grupo*, opción **La colisión acompaña a mallas / props**, activada por defecto): las cajas de colisión y las caras de piso / pared del `.hm` que están dentro de una malla o un prop:
  * se **mueven**, **giran** y **escalan** con él (con G / R / T, con los campos de la selección o moviendo un grupo; en un grupo cada pieza se mueve una sola vez);
  * se **copian** con él (Duplicar, Q, filas de copias, copia espejada). Con Q, la colisión de la copia se crea donde la soltás, no encima del original;
  * se **borran** con él: al borrar una malla o un prop se van también sus caras del `.hm`, no solo las cajas.

  Si la apagás, como antes: solo se mueve lo que se ve.
* **Mallas**: además de moverse, girarse y escalarse, ahora se escalan **distinto en cada eje** (por ejemplo 2 × 1 × 1), siguiendo sus propios ejes aunque estén giradas. Siguen sin poder girarse ni escalarse las mallas que son el molde de props: esas se editan desde sus props.
* **Armas una por una** (*Weapons allowed on this map*): en los grupos con varias armas (3: uzi / escopeta / rifle / cetme; 4: bazuca / lanzagranadas / ametralladora / lanzallamas / bengalas; 5: minas) elegís *la que elija cada jugador* o **solo** una. Por ejemplo, *cuchillo, pistola y rifle*: grupos 1, 2 y 3 con "solo rifle", 4 y 5 destildados. O *cuchillo, pistola y ametralladora*: 3 destildado y 4 con "solo ametralladora". La copia de la DLL se hace siempre desde la DLL original del juego: en vez de leer el arma que eligió cada jugador en su perfil, le da a todos esa arma (también la que tiene en la mano al nacer). No probado en el juego.
* **Puntos de aparición al piso**: en el panel de un `mp_CStartPoint`, *Al piso (donde hay colisión)* lo apoya sobre el piso de colisión que tiene debajo (20 unidades arriba, como los del juego; si está hasta 2,5 m por debajo de un piso, sube a ese piso). *Todos los puntos de aparición al piso* hace lo mismo con todos menos los bloqueados.
* **Color del punto de aparición seleccionado**: amarillo si es del equipo 0, **rojo** si es del equipo 1.
* **Map tools ordenadas**: arriba hay botones por categoría: *Todo, Construir, Colisión, Aspecto, Jugabilidad, Revisar, Juego y archivos*. Muestran solo las herramientas de esa categoría. Ctrl+P sigue buscando cualquiera por nombre.
* **Formas** (*Construir → Formas*): caja / cubo / rectángulo, cilindro, cono, rampa, escalera, pirámide, pared, disco, o **dibujadas por puntos**: contorno A, B, C… con altura (sirve cualquier forma, también cóncava), rectángulo por 2 esquinas, círculo por centro y borde. Los puntos se marcan con *Medir*.
  * Tamaño (ancho / alto / profundidad), giro, lados (redondez), escalones, textura de **relleno** (o la de *Relleno*) y cada cuánto se repite.
  * **Vista previa** en líneas amarillas en el lugar donde va a quedar, que se actualiza al cambiar cualquier valor, antes de apretar *Crear*.
  * Con *sólido* tiene colisión: cajas que siguen la forma y caras de piso / pared en el `.hm`. Rampa, escalera, cono y pirámide llevan solo caras de piso, para poder subirlas caminando. Queda seleccionada y se mueve / gira / escala como cualquier malla, con su colisión.

## 72. Mapas de Counter-Strike 1.6 (.bsp), vaciar una zona, armas una por una (nueva vista)
* **Importar un mapa de Counter-Strike 1.6** (*Map tools → Construir → Importar un mapa de Counter-Strike 1.6 (.bsp)*): elegís el `.bsp` (Half-Life / CS 1.6, versión 30) y lo pone en tu mapa:
  * una malla con textura por cada textura, con las mismas coordenadas de textura que en CS;
  * colisión: una caja detrás de cada cara (solo giradas en vertical, como las del juego), una caja alrededor de cada `func_wall` (las cajas de aim_map), y caras de piso / pared en el `.hm` (todas menos las que miran hacia abajo);
  * puntos de aparición desde sus `info_player_start` (CT → equipo 0) e `info_player_deathmatch` (T → equipo 1), mirando a donde miraban en CS, apoyados 20 unidades sobre el piso nuevo y corridos lo mínimo si quedaban pegados a un escalón; con *hacerlo deathmatch por equipos* la escena pasa a DMT;
  * se omiten `sky`, `aaatrigger`, `clip`, `null`, triggers, etc.

  **Escala**: 1 unidad de CS = 2,54 cm (tamaño real; el campo lo deja cambiar). **Giro**: 90° pone el eje Y de CS a lo largo del X del juego. **Lugar**: el centro del piso del mapa de CS va al punto elegido (*Ponerlo donde mira la vista* o escribiendo X/Y/Z). Antes de importar muestra cuánto ocupa (ancho × largo × alto).

  **Texturas**: el `.bsp` no trae las texturas (están en los `.wad` de CS), así que cada textura de CS se dibuja con una de Torrente. Viene una sugerida por el nombre (arena → `SUELOS_03`, paredes de arena → `catedra_muro`, cajas → `caja1` / `caja2`, hormigón → `muro_liso`, zócalos → `muro_base`, puerta → `porton_arabe`…) y cada una se puede cambiar (o poner la de *Relleno*) y elegir **cuántas veces se repite** donde la de CS se repetía una vez.
* **Vaciar una zona**: *vaciar el lugar antes* (en el importador) saca todo lo que está **entero** dentro de lo que va a ocupar el mapa nuevo: mallas, props, cajas de colisión, paredes del `.hm` y módulos (menos la cámara). **El piso queda** (las mallas y caras del `.hm` que no suben más de 15 unidades sobre el piso más bajo de ahí) y también lo que está solo en parte adentro (por ejemplo las gradas de un estadio). Lo bloqueado no se toca. Para una zona más grande: *Vaciar una zona: entre los puntos A y B de Medir*.
* **Armas una por una** (*Weapons allowed on this map*), ahora con **cada arma separada**: en cada grupo aparecen todas sus armas para elegir:
  * 1: cuchillo (siempre); 2: pistola (sí / no);
  * 3: uzi, escopeta recortada, rifle, cetme, *todas (elige cada jugador)* o *ninguna*;
  * 4: bazuca, lanzagranadas, ametralladora, lanzallamas, pistola de bengalas, *todas* o *ninguna*;
  * 5: minas de proximidad, minas remotas, *todas* o *ninguna*.

  Abajo dice cómo queda: por ejemplo *Este mapa: cuchillo, pistola, cetme, lanzagranadas, minas de proximidad*. En un grupo se puede elegir **una** arma o **todas**: el juego no tiene forma de dar dos armas de un grupo sin las demás. *Make weapons DLL for this map* hace la copia de la DLL del modo para ese mapa (desde la DLL original del juego). No probado en el juego.

### mp_dm_entrenamiento como aim_map (DMT 16 contra 16)
Hecho con esas herramientas: se vació el rectángulo de la cancha (las paredes `MUROS`, las columnas, los vidrios y los carteles que había adentro; quedan el césped, la línea del borde y todo el estadio), se importó `aim_map.bsp` en el centro de la cancha (escala real, 56 × 38 m, paredes de 8,7 m), 16 puntos del equipo 0 y 16 del equipo 1 donde estaban los de CS, y la escena pasó a **deathmatch por equipos** (`mp_deathMatchTeam.dll`, la del juego, va en el zip). Los botiquines del mapa original (fuera de la cancha) quedan como estaban.

## 73. Mapas nuevos desde un .bsp con sus texturas (.wad), destruir el objetivo con dos sitios (A y B)
* **Texturas del .wad**: en *Importar un mapa de Counter-Strike 1.6 (.bsp)* hay un campo *paquetes de texturas (.wad)* (varios separados con `;`, o *Buscar .wad...*). *Usar las texturas del .bsp / .wad* convierte cada textura que esté en el `.bsp` mismo o en esos `.wad` en una **textura nueva del juego** (`.tex`, llevada a tamaño potencia de 2, con mipmaps; las que empiezan con `{` quedan transparentes) y la pone en la tabla. Nunca reemplaza una textura del juego: si el nombre está ocupado por otra imagen, la nueva se llama `cs_<nombre>`. Las que no están en ningún `.wad` siguen con una textura de Torrente parecida (arena, paredes de arena, cajas, hormigón, zócalos, puertas, camino → `SUELO_coliseum1`, roca → `SUELOS_05`…).
* **Modo al importar**: *dejar el modo de la escena*, *deathmatch por equipos* o **destruir el objetivo (sus sitios de bomba A y B)**, y *puntos de inicio por equipo* (por ejemplo 16: de los que tenga el mapa se quedan los 16 más juntos de cada equipo, en sus lugares originales). Los puntos de inicio sin dirección en el mapa miran al centro del mapa. Se apoyan en el piso donde se camina, también en el borde de una rampa.
* **Destruir el objetivo con dos sitios**: con ese modo, cada `func_bomb_target` del mapa se vuelve una zona de bomba (`mp_BombZone`, el modelo y la configuración de la de *mp_do_ruinas*) en el piso del sitio, con un radio según su tamaño: la `tgt_a` se llama **`bombZone`** y la `tgt_b` **`bombZone_B`**.
  * El modo DO del juego (`mp_DestroyTheTarget.dll`) solo termina la ronda cuando explota el objeto llamado `bombZone`. La bomba ya se puede plantar en cualquier zona de bomba de la escena, pero si volaba la segunda, la ronda no terminaba. Por eso el editor hace una **copia de la DLL para ese mapa** (`mp_DestroyTheTarget_<mapa>.dll`) que también revisa `bombZone_B`: 9 instrucciones nuevas en el espacio libre del final del código, sin tocar nada más (ni relocaciones). La DLL del juego no se modifica. Hay que copiarla a la carpeta del juego en el servidor y en cada PC (el zip la trae y *Instalar mapa desde zip* la pone).
  * El radar sigue marcando solo `bombZone` (A).
  * *Map tools → Jugabilidad → Dos sitios de bomba*: lista las zonas, *Segunda zona de bomba acá (copia de bombZone)* y *Hacer la DLL que cuenta las dos*. Si después cambiás las armas del mapa, la copia nueva conserva la segunda zona.
  * El chequeo de modo acepta una zona, o dos con esa copia de la DLL.
* **Un mapa nuevo entero**: abrí un mapa del juego del modo que quieras (se quedan su cielo, el sol, la luz ambiente y la cámara), *Guardar como* con el nombre nuevo y después: **1. Vaciar este mapa** (saca mallas, props, decals, colisión, caras del `.hm`, luces puntuales y módulos), **2. Importar** en 0, 0, 0 y **3. Sectores nuevos** (arma de cero el árbol de sectores que usa el juego para saber qué dibujar, a medida del mapa nuevo).
* **Más rápido**: las cajas de colisión de un `.bsp` grande se agregan todas juntas (antes, con miles de cajas, tardaba minutos).

### mp_do_dust2 (de_dust2 de CS 1.6, DO 16 contra 16)
Hecho con esas herramientas a partir de `mp_do_madrid` (su cielo, su sol y su configuración): 21 mallas, 3540 cajas de colisión y 3352 caras de piso / pared. Las 13 texturas que trae el `.wad` adjunto (puertas y paredes con las flechas A / B, el piso de la X del sitio A, la roca, los créditos…) están convertidas. Las demás texturas de dust2 están en el `cs_dust.wad` de CS, que no vino, y por eso usan texturas de Torrente parecidas. 16 puntos de inicio por equipo en los lugares originales (CT → equipo 0, el que defiende en DO; T → equipo 1, el que ataca). Zonas `bombZone` en el sitio A y `bombZone_B` en el B, la bomba (`mp_Bomba`) en la base de los T, 3 botiquines en cada base y la cámara de inicio sobre el mapa. Modo DLL: `mp_DestroyTheTarget_mp_do_dust2.dll` (la copia que cuenta las dos zonas). No probado en el juego.

## 74. La prueba de caminar choca con autos, puertas y objetos de la escena
En el juego, los módulos con modelo (autos `mp_CCar`, puertas `mp_Door`, `RenderNFO`, `mp_Cosa` como `paredT.NFO`, `cglass`, la moto, el vagón del metro, las zonas de bomba…) son sólidos por su propio objeto, aunque el mapa no tenga cajas de colisión ahí. La prueba de caminar solo usaba el `.hm` y las cajas del mapa, así que el personaje los atravesaba.

Ahora el mundo de la prueba agrega cajas que siguen la forma de cada parte del modelo de esos módulos, giradas con el módulo (con su posición, giro y escala). Un par de barandas da dos cajas, no una que tape el paso. Se saltean las partes chicas (menos de 80 cm, como las gaviotas) y las enormes (más de 25 m, como el mar, las olas o el cielo). Lo mismo usan el chequeo de puntos de aparición (un punto adentro de un auto se marca), *Al piso*, la simulación de partida y las demás herramientas que miran por dónde se camina. Se puede pararse arriba (por ejemplo en el techo de un auto). Las cajas se recalculan solas cuando un módulo se mueve. Los objetos que se levantan (botiquines, armas, la bomba, banderas) y los puntos de aparición no chocan. Son cajas, no los triángulos: en objetos con huecos (un arco, un portón abierto) puede chocar un poco antes que en el juego. Las puertas se toman cerradas.

## 75. Cielo: todas las escenas que lo usan
En *Sky*, debajo del cielo elegido, ahora aparece **la lista completa** de las escenas que lo usan (*la usan N escenas:* y todos los nombres, que se acomodan en varias líneas). Antes mostraba solo las 3 primeras y "...". El mismo cielo escrito con otras mayúsculas (por ejemplo `CIELO_A.tex` y `cielo_a.tex`) ahora cuenta como uno solo: el número del desplegable y la lista coinciden.

## 76. Agua, puertas y vidrios de los mapas de CS; puntos de inicio repartidos por todo el piso
* **Entidades de los `.bsp`**:
  * `func_water` (piletas, agua): se dibuja **semitransparente** (con la transparencia del mapa, `renderamt`) y su superficie es **piso**: como en Torrente no se nada, se camina sobre el agua en vez de quedar atrapado en el fondo. No tiene cajas de colisión.
  * `func_door` / `func_door_rotating`: las puertas quedan **abiertas** (no se ponen; en el juego no se abrirían). Si un brush tiene `origin`, se lo pone en su lugar.
  * `func_illusionary`: se ve, pero se atraviesa.
  * Vidrios y otros brushes con `rendermode` de textura y `renderamt` menor a 255: su textura sale semitransparente cuando la convierte *Usar las texturas del .bsp / .wad* (solo si esa textura no se usa también en algo sólido).
  * Triggers, zonas de compra y de rehenes, escaleras invisibles, etc.: no se ponen.
* **Repartir puntos de inicio por todo el piso** (*Map tools → Jugabilidad → Revisar puntos de inicio*, abajo): *N puntos de inicio* + **Repartirlos por todo el piso**. Reemplaza los puntos de inicio por N nuevos, lo más separados posible entre sí, en **todos los pisos a los que se puede ir caminando desde los actuales y volver** (no en un pozo ni arriba de un techo sin subida). Siempre sobre el piso mismo (no arriba de una caja o un mueble), 20 unidades sobre él, con lugar alrededor (sin pared, caja ni objeto a menos de 40 unidades), nunca en el agua, mirando al centro del mapa. Equipos alternados 0 / 1. Los bloqueados se quedan.
* En el importador, el modo **deathmatch (puntos de inicio por todo el piso)** hace eso solo, con tantos puntos como tenían los dos equipos juntos (o 2 × *puntos por equipo*).
* *Sectores nuevos* ahora también abarca dónde están los módulos (la cámara de inicio queda dentro del área de sectores).

### mp_dm_pool_day y mp_dmt_pool_day (fy_pool_day de CS 1.6, de Squall)
Hechos a partir de `mp_dm_madrid` / `mp_dmt_madrid` (cielo, sol y configuración): las 26 texturas que trae el `.bsp` (azulejos, casilleros, el cartel de reglas, la pileta…) convertidas, la pileta semitransparente y caminable por arriba, las puertas abiertas.
* **DMT**: 16 contra 16 en las dos bases originales (CT → equipo 0, T → equipo 1), 3 botiquines en cada base.
* **DM**: 32 puntos de inicio repartidos por todo el piso, todos en el piso de la planta baja, separados al menos 1,2 m, ninguno en la pileta; 6 botiquines también repartidos entre ellos.

Los zips traen `creditos_fy_pool_day.txt` con las notas originales del autor (el instalador lo ignora). No probados en el juego.

## 77. Mapas negros en el juego, piletas como huecos, el importador de CS arreglado, mapa nuevo desde cero
* **Mapas negros en el juego (mp_do_dust2, mp_*_pool_day)**: no eran las luces (tienen dos soles y la luz ambiente de Madrid). Las mallas nuevas copiaban el **bloque de color del material** (ambiente / difuso / especular) de otra malla del mapa. En un mapa recién vaciado no había ninguna, así que quedaba **todo en cero**, y el juego dibuja esos materiales negros con cualquier luz (en el editor se veían bien). Ahora un material nuevo sin otra malla de donde copiar lleva el bloque de los materiales del juego (ambiente 1, difuso 0,68, especular 1), igual que todos los de los mapas originales. También pasa con las formas, el relleno y los OBJ importados.
  * *Revisar el mapa* lo marca como error (*N meshes tienen un material sin color…*), y *Map tools → Aspecto → Texturas* tiene **Arreglar materiales negros** para los mapas ya hechos.
  * *Revisar el mapa* también avisa si el mapa no tiene ni sol ni luz ambiente.
* **Piletas como huecos** (importador: *agua (piletas)* → **un hueco: el que entra se cae fuera del mapa**): no se pone el agua ni el fondo de la pileta, las paredes de la pileta se ven pero no son sólidas, y a los pisos y techos que hay debajo se les recorta el rectángulo de la pileta (con sus coordenadas de textura), así que no queda nada donde caer: se cae fuera del mapa. Los puntos de inicio y los botiquines nunca quedan arriba de un hueco (los repartidos solo van donde hay piso y se puede volver; *Revisar puntos de inicio* marca *sin piso abajo*). La otra opción, *un piso*, es la de antes.
* **Importar un mapa de CS 1.6 no funcionaba**: el panel se cortaba al dibujar la tabla de texturas (faltaba una función del editor) y no llegaba al botón *Importar*. Arreglado y probado apretando los botones de verdad.
* **Mapa nuevo desde cero** (*Map tools → Construir → Mapa nuevo desde cero (suelo y paredes)*):
  * nombre, modo (deathmatch, por equipos, captura la bandera, destruir el objetivo; el nombre toma el prefijo del modo), forma (**rectángulo, cuadrado, círculo, octógono, L**), medidas en cm (ancho y profundidad, o lado o diámetro), alto y grosor de las paredes, texturas del suelo y de las paredes (o la de *Relleno*), jugadores por equipo;
  * **Crear el mapa nuevo** hace la escena con su propio `.opt` y `.hm` (cielo, sol y configuración de la escena de Madrid de ese modo), el **suelo** (una losa de 30 cm con colisión), las **paredes** alrededor (una por lado, solapadas en las esquinas, con colisión), y lo del modo:
    * DMT / B / DO: los jugadores de cada equipo en filas en las dos puntas del lado más largo, mirando al centro;
    * DM: el doble de puntos de inicio, repartidos por todo el suelo;
    * B: las banderas detrás de cada base; DO: la zona de bomba del lado del equipo 0 y la bomba del lado del equipo 1;
    * 4 botiquines, la cámara de inicio y los sectores. Queda guardado y abierto.

### Mapas rehechos
`mp_do_dust2`, `mp_dm_pool_day` y `mp_dmt_pool_day` con los materiales con color. Las dos de pool_day tienen las piletas como huecos: ningún punto de inicio ni botiquín sobre ellas. No probados en el juego.

## 78. Armas una por una: cada arma con su propia munición
El problema: un arma fijada por el mapa (por ejemplo, solo cetme en el grupo 3) recibía la munición del arma que el jugador había elegido en el menú del juego. Si elegía la uzi, el cetme salía con las 210 balas de la uzi (6 cargadores) en vez de sus 120 (3 cargadores).

El juego da la munición en dos momentos:
* **Al crearse el jugador**: las balas que su perfil tiene para el arma que eligió en el menú.
* **Al renacer**: una tabla de la DLL del modo, buscada con el arma de su perfil.

La copia de la DLL ahora, en cada grupo con un arma fijada:
* al crearse, le da **las balas de esa arma** según la tabla de la misma DLL (por ejemplo, cetme 120, uzi 210, escopeta 30, rifle 20, bazuca 2, lanzagranadas 4, ametralladora 50, lanzallamas 200, pistola de bengalas 10, minas 4);
* al renacer, busca la tabla con **el arma fijada**, no con la del perfil.

Así un arma fijada siempre tiene la misma munición que cuando se la elige normalmente en el menú, elija lo que elija el jugador. Los grupos sin arma fijada quedan con el código original del juego. Si se rehace la DLL con otra arma, o con *la que elija cada jugador*, la munición también cambia o vuelve a la original. En *Weapons allowed on this map* se ve cuántas balas recibe cada arma fijada. No probado en el juego.

## 79. Colisiones invisibles en las rampas de los mapas de CS; las piletas-hueco ahora hacen caer
* **Paredes invisibles en mp_do_dust2** (en el medio, saliendo de la base de un equipo, en la rampa de la base del otro): cada cara del `.bsp` llevaba detrás una caja de colisión, y como las cajas del juego solo giran en vertical, la caja de una **rampa** (o de una pared de roca inclinada) quedaba parada sobre ella como una pared invisible a la altura de su punto más alto. dust2 tiene 585 caras inclinadas. Ahora las cajas son solo para caras verticales (hasta 10° de inclinación) y pisos planos; las rampas y paredes inclinadas son sólidas por sus caras del `.hm`, que es lo que usa el juego para caminar. En la prueba de caminar del editor, antes desde la base T no se llegaba a ningún sitio; ahora se llega a A (≈134 m), a B (≈123 m) y a la base CT.
* **Las piletas-hueco no hacían caer** (mp_*_pool_day): el juego solo deja caer a un jugador si abajo hay algún piso; sin nada abajo, se camina por encima del hueco. Ahora, 60 m debajo de cada pileta-hueco hay un piso invisible del tamaño de la pileta: el que entra cae y no sobrevive la caída. Los puntos de inicio repartidos nunca van ahí (no se puede volver).
* Rehechos: `mp_do_dust2`, `mp_dm_pool_day`, `mp_dmt_pool_day` y también `mp_dm_entrenamiento` / `mp_dmt_entrenamiento` (aim_map tenía algunas caras inclinadas). No probados en el juego.

## 80. Texturas de cualquier .wad en el importador; mp_dmt_aim_map
* En la tabla de texturas del importador de `.bsp` se puede escribir el **nombre de una textura de los `.wad` cargados** (por ejemplo `out_snd1` de `halflife.wad`): al importar se convierte en una textura nueva del juego, sin reemplazar ninguna, y se usa para esa textura de CS. Sirve cuando el `.wad` no tiene las texturas propias del mapa.
* **mp_dmt_aim_map**: aim_map como mapa propio (su escena, `.opt` y `.hm`, con el cielo y el sol de `mp_dmt_madrid`), deathmatch por equipos, 16 contra 16 en los lugares originales de cada lado (CT → equipo 0, T → equipo 1), 4 botiquines, la cámara de inicio y los sectores nuevos. Las texturas propias de aim_map (`-0Sand`, `csSandWall`, `SandCrt…`, `MltryCrte…`) están en `cs_dust.wad` de Counter-Strike; `halflife.wad` no las tiene, así que se dibujan con las más parecidas de ese `.wad`: arena `out_snd1`, paredes `out_wall1a`, hormigón `out_wall8`, zócalos `out_wall9`, puerta `out_w1dr1`, cajas `crate01` / `crate02` / `crate05` y las militares `xcrate9d`. Con `cs_dust.wad` se pueden poner las originales. No probado en el juego.

### Con cs_dust.wad
`mp_dmt_aim_map` y `mp_do_dust2` rehechos con sus texturas originales de `cs_dust.wad` (arena, paredes de ladrillo arenoso, zócalos, cajas de madera y militares, puertas, camino). En dust2 las últimas tres que no están ahí (`white`, `generic011`, `~fifties_lgt2`) salen de `halflife.wad`. Todas son texturas nuevas del juego (si un nombre ya existe con otra imagen, la nueva lleva `cs_` delante). No probados en el juego.

## 81. Varios .wad a la vez en el importador de mapas de CS 1.6
En *Importar un mapa de Counter-Strike 1.6 (.bsp)*, los paquetes de texturas son ahora una **lista**:
* **Agregar .wad (varios a la vez)...**: el selector deja marcar varios archivos juntos (Ctrl / Shift + clic).
* **Agregar todos los .wad de una carpeta...**: por ejemplo la carpeta `cstrike` o `valve` del juego, con todos sus `.wad` de una vez.
* Cada `.wad` de la lista muestra cuántas texturas tiene y **cuántas son de este mapa**. Con la **x** se saca uno de la lista, y *Limpiar* la vacía. Un `.wad` repetido no se agrega dos veces.
* Abajo se ve cuántas de las texturas del mapa están en los paquetes cargados, por ejemplo *13 de las 13*.
* Si dos paquetes tienen una textura con el mismo nombre, se usa la del primero de la lista.

*Usar las texturas del .bsp / .wad* y los nombres de texturas de `.wad` escritos en la tabla buscan en todos los de la lista.

## 82. Colisiones de los mapas de CS sacadas de su "clip hull" (lo que el jugador choca en CS)
Hasta ahora las paredes y pisos del `.hm` salían de las caras **visibles** del `.bsp`. Pero en CS lo que el jugador choca no son las caras que se ven: el `.bsp` guarda aparte el **clip hull** (hull 1 = jugador de pie), que tiene todos los bloques sólidos **más los bloques CLIP invisibles** que puso el autor del mapa:
* **Escaleras**: en CS casi todas tienen encima una rampa CLIP invisible para subirlas sin saltitos. Ahora esa rampa está en el `.hm`, así que se suben igual que en CS.
* **Paredes invisibles del autor** (bordes del mapa, techos y cornisas a los que no se debe subir, esquinas suavizadas): ahora también frenan al jugador, como en CS.
* **Objetos que se chocan** (cajas, barriles, autos, columnas, puertas fijas, barandas hechas con `func_wall`): salen del hull con su forma real, también los que tienen partes inclinadas o redondeadas.
* Lo que en CS no se choca sigue sin chocarse: `func_illusionary`, agua, zonas de compra/bomba, puertas que se abren, escaleras de mano (`func_ladder`, el juego no tiene trepar).

Cómo se hace: el hull de CS es el sólido "engordado" por la caja del jugador (32 × 32 × 72 unidades). El importador recorre el árbol del hull, toma el borde exacto entre lo sólido y lo vacío y lo devuelve a su lugar real: cada cara se corre la medida de la caja; donde la superficie dobla hacia afuera (el borde de un escalón, de una cornisa) se recorta, y donde se encuentra con otro sólido (una pared parada sobre el piso) se alarga, así las paredes llegan hasta el piso y los pisos hasta las paredes, sin rendijas. Si lo que hay al otro lado de un borde cambia a mitad de camino (un piso que corre a lo largo de una pared que se termina), la cara se parte ahí. Las cajas de colisión del juego siguen saliendo de las caras visibles (paredes verticales y pisos planos, nunca en rampas).

Si el `.bsp` no tiene clip hull (por ejemplo uno compilado sin él), se usa como antes las caras visibles.

Mapas rehechos con esto: `mp_do_dust2`, `mp_dmt_aim_map`, `mp_dm_pool_day`, `mp_dmt_pool_day` (las piletas siguen siendo huecos con el piso mortal debajo). En la prueba de caminar del editor se llega desde la base T a A, a B y a la base CT en dust2, y de base a base en aim_map y pool_day. **No probado en el juego.**

## 83. Destruir el objetivo: el tiempo de la bomba y qué pasa a las 0:00
En **Map tools > Jugabilidad > Destruir el objetivo: sitios de bomba y la bomba**, debajo de las zonas, está **La bomba**:
* **Segundos desde que se planta hasta que explota** (el juego trae 20).
* **A las 0:00 esperar a una bomba plantada** (casilla): si el reloj llega a 0:00 con una bomba plantada, la ronda no termina. El reloj pasa a mostrar los segundos que le quedan a la bomba (+1). Si explota, ganan los atacantes; si la desactivan, el reloj se acaba otra vez y ganan los defensores. Es como en CS.
* **Qué hace el juego sin esto** (revisado en sus DLL): el tiempo de la C4 **no se suma al reloj**. A las 0:00, `mp_ContadorTiempo` avisa `__timeout__` y la DLL de DO termina la ronda en ese momento: ganan los defensores aunque la bomba esté plantada.

Las dos cosas van en la copia de la DLL de modo del mapa (`mp_DestroyTheTarget_<mapa>.dll`, donde también están la segunda zona y las armas). Hay que copiarla en la carpeta del juego, en el servidor y en la PC de cada jugador; la exportación del mapa la incluye.

**Corrección (la primera versión no funcionaba en el juego):** la bomba que se planta **no es** la `bomba` de la escena, que es solo la que se levanta del piso. Al plantar, el arma bomba (`mp_bomb.dll`) crea un objeto nuevo con la `mp_bomba.dll` del juego, buscándola por nombre, y lo agrega a la lista de bombas de la escena. Por eso la copia `mp_Bomba@<mapa>.dll` nunca se usaba, y la espera a las 0:00 miraba un objeto que nunca está "plantado". Ahora la DLL de modo tiene dos cambios:
* en `Run` de la escena (cada cuadro, en todas las PC): a cada bomba de la lista que está corriendo y todavía no se tocó, le corre la hora de plantado (`+0x194`, y `+0x1D8`, la de limpieza) por (tiempo − 20 s). Así explota a los segundos elegidos. Las que ya se corrigieron se anotan en 64 bytes libres al final de `.data`;
* en `__timeout__`: si hay una bomba de la lista corriendo (`+0x1B0` = 1), pone en el reloj sus segundos y no termina la ronda. Como el reloj se frena solo después de avisar, el siguiente `Run` lo vuelve a poner en marcha.

El editor vuelve las `bomba` de la escena a la `mp_Bomba.dll` del juego (la copia `@` ya no hace falta). **No probado en el juego.**

## 84. Armas: varias de un mismo grupo
En **Armas permitidas en este mapa**, cada grupo de varias armas tiene ahora una casilla por arma (y los botones *todas* / *ninguna*). Se pueden permitir, por ejemplo, la cetme y el rifle, pero no la uzi ni la escopeta.
* El menú del juego sigue mostrando todas. Si un jugador elige una que no está tildada, recibe **la primera tildada, con su propia munición** (la de la tabla de la DLL: cetme 3 cargadores, rifle 20...). Si elige una tildada, la recibe con la munición de siempre.
* Cómo funciona: cada lectura de la elección del jugador en la DLL (al crearse, al renacer, la tabla de munición, el arma en la mano) pasa antes por un control que corrige la elección si no está permitida. La copia guarda las instrucciones originales, así que se puede cambiar otra vez.
* Una sola tildada sigue siendo "solo esa arma" (como antes). Todas tildadas: cada jugador elige.
* Como antes, solo con las DLL de capturar la bandera (las de DM, DMT y DO no reparten las armas de la forma conocida). **No probado en el juego.**

## 85. Importar CS 1.6: texturas directo del .bsp / .wad, y mapas .rmf
**Map tools > Construir > Importar un mapa de Counter-Strike 1.6 (.bsp / .rmf)**:
* **Texturas: "las suyas"** (por defecto) saca cada textura del mismo .bsp o de los .wad cargados y la convierte; las que nadie tiene se dibujan con una textura de Torrente parecida. Ya no hace falta completar la tabla textura por textura. La tabla sigue estando en la opción "texturas de Torrente (elegir una para cada una)".
* **Qué .wad necesita el mapa**: un .bsp nombra sus paquetes (`halflife.wad`, `cs_dust.wad`...). El panel los lista en verde (cargado), amarillo (encontrado junto al mapa o en las carpetas `valve` / `cstrike` de Half-Life, con el botón **Cargar los N encontrados**) o rojo (no cargado). También dice cuántas texturas están dentro del mapa, cuántas en los .wad y cuántas faltan (pasando el mouse se ven sus nombres). Los .wad cargados se recuerdan para la próxima vez.
* **Mapas de Hammer (.rmf, versión 2.2)**: se leen los bloques (brushes) y entidades sin compilar, y se hace lo mismo que el compilador de CS:
  * se cortan las partes de las caras tapadas por otros bloques;
  * se sacan las caras que dan al vacío de afuera del mapa (relleno desde los nacimientos, si el mapa está cerrado);
  * no se dibujan las texturas de herramienta (CLIP, NULL, SKY, HINT, AAATRIGGER...);
  * `func_detail` va como mundo;
  * las coordenadas de textura salen de los ejes de Hammer: con de_dust2 coinciden con las del .bsp compilado.
  
  La colisión es el contorno de todos los bloques sólidos juntos, incluidos los CLIP (rampas de escalera, paredes invisibles); HINT, SKIP, triggers y agua no son sólidos. Un .rmf no dice qué .wad usa: cargalos a mano.

## 86. Crear un mapa nuevo desde .bsp / .rmf
**Archivo > Mapa nuevo desde CS 1.6 (.bsp / .rmf)...** (o **Map tools > Construir > Crear desde .bsp / .rmf**, o el botón *Un mapa nuevo entero a partir de este...* del importador):
1. Elegir el .bsp o .rmf. El panel muestra qué .wad pide y cuáles faltan, para cargarlos ahí mismo.
2. Elegir el modo (DM, DMT, capturar la bandera, destruir el objetivo), el nombre (se propone `mp_<modo>_<mapa>`), los jugadores por equipo y qué hacer con el agua (piso o hueco).
3. **Crear el mapa nuevo** hace todo y lo guarda:
   * el cielo, sol y configuración de la escena Madrid de ese modo;
   * el mapa a tamaño real con sus texturas y la colisión de CS;
   * los nacimientos (CT equipo 0, T equipo 1; en DM repartidos por todo el piso);
   * botiquines junto a cada base;
   * las banderas detrás de cada base (capturar la bandera), o los sitios de bomba A y B con su DLL y la bomba junto a los terroristas (destruir el objetivo; si el mapa no tiene sitios, una zona cerca de los defensores);
   * sectores nuevos y la cámara de inicio.

Probado en el editor con de_dust2 desde el `.rmf`: los 32 nacimientos quedan bien y en la prueba de caminar se llega de la base T a A, a B y a la base CT, con las mismas distancias que con el `.bsp`.

## 87. Escaleras, rampas y escalones que el juego no dejaba subir; agua en las piletas
Los videos mostraban tres problemas distintos. Los tres están corregidos en el importador, así que sirven para cualquier mapa de CS que se importe:
* **Escalones**: en CS un jugador sube solo cualquier escalón de hasta 18 unidades (46 cm); en Torrente se frena con mucho menos (no subía al trampolín de pool_day, de 33 cm, ni las escaleras de dust2, de 40 cm). Ahora cada escalón bajo (con piso arriba y piso adelante) se convierte en una rampa corta en el `.hm` (unos 27°), apoyada en el piso de abajo y solo donde hay piso. Por ejemplo, el trampolín tiene rampa desde el borde de la pileta, pero sobre el agua sigue siendo un borde.
* **Rampas**: el compilador de CS "engorda" los pisos y las rampas hacia arriba (36 unidades), no a lo largo de su inclinación. Leer el clip hull suponiendo lo segundo dejaba la rampa de aim_map 28 cm por debajo de la que se ve, con un hueco abajo y un escalón de 30 cm arriba. Ahora vuelve exactamente a su lugar (medido en los .bsp: la diferencia es de menos de 1 cm). Además se corrigió:
  * un piso que sigue en una rampa suave ya no se recorta (en dust2 quedaba un hueco de 90 cm en medio);
  * el lado de una tabla fina cortada por el árbol del hull ya no sale como una pared de 58 cm sobre la tabla.
* **Cajas de colisión**: ya no salen de lo que se dibuja (que ponía cajas detrás de cada escalón, de cada borde de rampa y debajo de cada piso, aunque en CS esas colisiones no existen). Ahora salen de las paredes reales del hull: solo paredes más altas que un escalón y, cuando la pared tiene la parte de arriba inclinada (el costado de una rampa), en tramos que nunca sobresalen de la rampa.
* **Agua**: con las piletas como hueco, ahora se dibuja la superficie con el agua del Love Boat (`agua.tex`, semitransparente), y también el fondo y las paredes de la pileta. No tienen colisión: quien entra cae afuera del mapa, como antes.

Se comprobó con la prueba de caminar usando un escalón máximo de 20 cm (más exigente que el del juego):
* dust2: de la base T se llega a A, a B y a la base CT, con las mismas distancias que con 45 cm;
* aim_map: se llega a las dos rampas y balcones;
* pool_day: se llega al trampolín y al botiquín.

**No probado en el juego.**

Los mapas entregados (`mp_do_dust2`, `mp_dmt_aim_map`, `mp_dmt_pool_day`, `mp_dm_pool_day`) usan las escenas que mandaste (nacimientos, botiquines y cámara movidos). A dust2 se le devolvieron las dos zonas de bomba, la bomba y su DLL de modo (`mp_DestroyTheTarget_mp_do_dust2.dll`), porque la escena que llegó no las tenía y usaba la DLL del juego: sin ellas no hay objetivo, y con la DLL del juego la zona B no termina la ronda.

## 88. Destruir el objetivo: ganar volando todas las zonas; buscador de escenas y mapas; cómo funcionan los mapas DO del juego

### Bomba a las 0:00 (el reporte de los 10 segundos)
Lo que pasaba en tu prueba (bomba plantada con 10 s, a las 0:00 gana el rojo y los 40 s no se suman) era la primera versión del parche, que no funcionaba: miraba la `bomba` de la escena y no la que se planta (ver la corrección de §83). La DLL de `mp_do_dust2` que va en el zip está rehecha con la versión nueva: bomba de 40 s, el reloj espera a la bomba, y las zonas A y B. Se revisó desensamblando la DLL resultante. **No probado en el juego.**

### Ganar solo volando todas las zonas
En **Destruir el objetivo: sitios de bomba y la bomba**:
* **Ahora:** muestra lo que hace la DLL del mapa: la del juego (solo cuenta `bombZone`), *cualquiera gana*, o *hay que volar TODAS*.
* **Otra zona de bomba acá:** agrega una zona más (copia de `bombZone`) donde está la cámara, sin borrar las que ya hay. Se llaman `bombZone`, `bombZone_B`, `_C`, `_D` y `_E`: hasta 5 zonas.
* **Para ganar, volar TODAS las zonas de bomba antes de que termine el tiempo** (casilla) y **Hacer la DLL que cuenta todas las zonas**:
  * **destildada** (como el juego): los atacantes ganan cuando explota cualquier zona;
  * **tildada**: una zona que explota no termina la ronda. Ganan los atacantes cuando explota la última. Si el reloj llega a 0 antes (y no hay una bomba corriendo, si está la espera de §83), ganan los defensores.

Cómo está hecho: en la DLL de DO, donde el juego pregunta si `bombZone` está destruida (`+0x178`), se salta a código nuevo que busca cada zona por nombre (`ObjectByName`):
* en modo "cualquiera", basta una destruida;
* en modo "todas", tienen que estarlo `bombZone` y todas las demás. Una zona con nombre que no está en la escena no cuenta.

Se probó corriendo ese código en un emulador chico dentro de los tests, con todas las combinaciones de zonas destruidas o no, y junto con el parche de la bomba.

**Importante:** la bomba plantada se gasta. El arma la saca del jugador (`RemoveWeapon`) y la bomba se levanta del piso (la `bomba` de la escena, `bomba_target.nfo`). Por eso, con "todas", la escena recibe una bomba para levantar por cada zona (`bomba_2`, `bomba_3`..., copias de la primera, en el mismo lugar). No pude comprobar sin el juego si una bomba levantada vuelve a aparecer, ni si dos bombas plantadas en la misma ronda se llevan bien en red. **No probado en el juego.**

### Buscador en la lista de escenas y de mapas
En **Scene list** y **Maps list** (ventana DEBUG) hay un cuadro **search**, igual al de los módulos. Al escribir, quedan solo los nombres que tienen todas las palabras escritas, sin importar mayúsculas (por ejemplo, `do dust`). Muestra "N de M" y la **x** lo borra.

### Los mapas DO del juego: qué tienen en común y en qué cambian
Todas las DLL de DO del juego (`mp_DestroyTheTarget`, `mp_DestroyAlmacen`, `Garaje`, `Loveboat`, `TheMArb`, `TheMarbMO`, `Theghotic`, `Vertigo`) son **el mismo programa**: mismo tamaño (94 208 bytes) y cambian en 1 a 32 bytes. Lo que cambia es el nombre de mapa con el que se activan dos comportamientos especiales:
* **Tipo "plaza"** (por etapas): se activa con `nfos\mp_do_plaza.opt`; en las copias, el nombre propio del mapa (almacén, garaje, gótico, vértigo, marb MO). Hay botones (`Boton_portonarabe_01`, `_b`, `_b_2`, `_c`, `_c_02`, `_d`) que abren puertas por etapas, con una fase guardada en la DLL. Al pasar de etapa se suman 3 minutos al reloj. La ronda se gana al destruir `BombZone_final`.
* **Tipo "asalto"**: se activa con `nfos\mp_do_asalto.opt`. Otra configuración de reloj y fase, pero con `bombZone`.
* **Normal**: todos los demás. Una sola zona llamada `bombZone`: cuando se destruye ganan los atacantes, y a las 0:00 ganan los defensores.
* **Retoques puntuales:**
  * Almacén silencia una frase de voz (`frase_3_esp.wav`);
  * Love Boat cambia la cámara `camara_seg` por `mp_meneo.dll` (el bamboleo del barco);
  * TheMArb cambia un caso de un `switch`.

Escenas:
* **Una sola `bombZone` con `mp_DestroyTheTarget.dll`:** anderguater, asalto, chino, comercial, laberinto, madrid, metro, moonlight, museo y ruinas.
  * Con `bomba` para levantar: asalto, chino, comercial, madrid y museo.
  * Con paredes `Pared_*` que se rompen: madrid, chino y metro.
* **`BombZone_final` con botones y puertas, con DLL propia:** almacén, garaje, gótico, multimarb y vértigo. Plaza usa la DLL general, que la reconoce por el nombre.
* **Una sola `bombZone` con DLL propia:** loveboat y marb.

En todos, la bomba que se planta la crea el arma (`mp_bomb.dll`) con la `mp_bomba.dll` del juego y va a la lista de bombas de la escena; explota a los 20 s. Por eso el parche de tiempo y el de zonas funcionan sobre cualquiera de estas DLL. Las de tipo "plaza" ganan con `BombZone_final` en la última etapa, no con `bombZone`, así que en esos mapas la opción de zonas no cambia nada.

## 89. Agujeros en el piso que tiraban afuera del mapa; menú Help > About

### El borde de la zona A de dust2 (el video)
En la esquina de la zona hundida de A, al subir por el borde, el jugador caía afuera del mapa ("se ha suicidado"). Pasaba porque el piso del `.hm` tenía un agujero de unos 20 a 40 cm sin ningún piso abajo, y el juego tira al vacío a quien no tiene piso debajo.

Esos agujeros quedaban al recortar los pisos del clip hull en la esquina de un escalón o de un borde: una muesca o una cuña finita. En CS no importan, porque ahí el jugador se apoya en el hull del bloque de al lado. En dust2 había varios (también al lado de B y en otros bordes), en aim_map 11 y en pool_day 2.

El importador ahora hace dos cosas con todos los mapas que se importen:
* **Cierra los huecos chicos.** Mira los pisos desde arriba en una grilla de 3 cm. Todo hueco angosto (menos de 70 cm de ancho en cualquier punto, aunque sea largo) recibe un piso a la altura del piso más bajo que lo rodea, así que nunca queda por encima de los pisos de al lado. Lo mismo pasa con un agujero chico en un piso de arriba que deja caer a uno de abajo. Las aberturas anchas (pozos, piletas, afuera del mapa) se dejan como están: el interior de un sólido nunca es tan angosto, porque el hull agranda todo por el ancho del jugador.
* **Cierra las juntas.** Cada piso se extiende 1,5 cm más allá de sus bordes, así que una junta más fina que la grilla tampoco queda abierta.

Los cuatro mapas entregados (`mp_do_dust2`, `mp_dmt_aim_map`, `mp_dm_pool_day`, `mp_dmt_pool_day`) están rehechos con esto. Llevan tus escenas tal cual estaban en la última entrega, y dust2 lleva su DLL de modo de §88 (40 s, espera a la bomba, zonas A y B). Comprobado:
* después del cambio no queda ningún agujero a 15 m de las dos zonas de dust2;
* la prueba de caminar con escalón de 20 cm sigue llegando a A, a B y a la base contraria.

**No probado en el juego.**

### Help > About
En la barra de menú hay **Help** (Ayuda) con **About** (Acerca de). Abre una ventana con:
* el nombre y la versión del programa (`VToyEditor Plus+ v1.0`, la misma de las propiedades del `.exe`);
* el ícono del programa, centrado: el `.png` de la carpeta `icon` si existe, o el dibujado;
* "Realizado por Lahrenheit";
* el enlace `https://github.com/Lahrenheit`, que se abre en el navegador al hacer clic.

**OK** o **Esc** la cierra. Los datos están en `vtoy/__init__.py` (`APP_NAME`, `APP_VERSION`, `APP_AUTHOR`, `APP_URL`).

## 90. Destruir el objetivo: "todas las zonas" corregido, zonas en el HUD, y el error "no room" al aplicar la bomba

### Por qué la ronda no terminaba al volar A y B
El flag "zona destruida" que mira la DLL del juego (`BombZone +0x178`) **solo está prendido mientras la zona explota**. Dura unos 60 cuadros: después `ExplosionMove` lo vuelve a 0 y queda mostrado el modelo destruido. El juego gana en el primer cuadro de la explosión, así que con una sola zona no se nota. Con "todas las zonas", en cambio, cuando explotaba la segunda la primera ya había vuelto a 0, y nunca estaban las dos destruidas a la vez.

Ahora una zona cuenta como destruida mientras explota **o** mientras se ve su modelo destruido. Ese modelo es el actor `[zona+0x164]`; su byte de visible (`+0x64`) es lo que devuelve `ActorGetVisible`. Así queda destruida hasta el reinicio de la ronda, que vuelve a mostrar el modelo entero.

### Las zonas en el HUD
Casilla **"mostrar las zonas de bomba en el HUD"** (tildada por defecto).
* Pone un ícono por zona arriba a la derecha de la pantalla, donde mp_do_plaza muestra sus objetivos.
* Los íconos son los de mp_do_plaza: `armas_grupo_345.tex`, el entero y el destruido.
* Cada ícono cambia al de destruido cuando su zona explota.
* Solo aparece en el DO común: plaza y asalto ya tienen lo suyo.

### Cómo está hecho
El código nuevo va en una **sección propia** de la copia de la DLL (`.vtoyz`, 4 KB, agregada al final del archivo), en vez de en el poco espacio libre al final de `.text`. Tiene dos ganchos:
* la prueba de "zona destruida" del `Run` de la escena;
* el final del constructor de la escena, que crea los íconos con `ConvertPixelToRender` + `AddSprite`, igual que plaza.

No depende de dónde cargue Windows la DLL. El fuente está en `tools/asm/bombzones.s` y `tools/asm/build.sh` lo arma.

Se probó de dos formas:
* **Ejecutando el código de verdad** como programa de 32 bits en Linux, con el juego simulado (zonas, actores, `ObjectByName`, `AddSprite`, `SpriteSetVisible`): modo cualquiera, modo todas, una zona que ya explotó (flag apagado y modelo destruido visible), zona ausente, los íconos y su cambio. Es `tools/asm/harness.c`, y lo corre `tests/test_batch14.py`.
* **Revisando la DLL armada:** los ganchos saltan a la sección, y cada dirección que usa el código es la import correcta o la textura correcta.

### "make_bomb_dll failed: no room for the new code"
La copia de la DLL se modificaba encima de sí misma con cada botón. Una copia hecha por una versión anterior del editor (con el código en otro lugar) o una secuencia de cambios dejaba la cuenta del espacio libre mal hecha.

Ahora **cada botón rehace la copia desde la DLL original del juego** (`mp_DestroyTheTarget.dll`), con las zonas y el tiempo de bomba que ya tenía, más el cambio pedido. Además, el cálculo del espacio libre mira lo que realmente hay en el archivo.

### mp_do_dust2
El zip entregado viene con:
* A y B, y hay que volar **las dos**;
* las zonas en el HUD;
* bomba de 40 s y el reloj que espera a la bomba;
* dos bombas para levantar (`bomba` y `bomba_2`).

Si querés volver a "cualquiera gana", destildá la casilla y apretá **Hacer la DLL que cuenta todas las zonas**.

**No probado en el juego.**

## 91. dust2: el agujero de la pared de B (pasar agachado, balas) y las piedras donde uno se trababa

### El agujero
El agujero de la pared entre B y las piedras mide entre 1,15 y 1,5 m de alto. En CS se pasa agachado. La colisión salía del "clip hull" del jugador **parado** (72 unidades de alto), y para ese hull un hueco más bajo que el jugador no existe: CS lo rellena. Por eso en el `.hm` había una pared entera ahí, que también frenaba las balas.

Ahora la colisión sale del hull del jugador **agachado** (hull 3, 36 unidades de alto, `COLLISION_HULL = 3`).
* Pisos, paredes y rampas quedan igual: el hull se devuelve a la superficie real, ahora con 18 de alto en vez de 36.
* Los pasos que en CS solo se hacen agachado ahora están abiertos: piso en el agujero y nada que tape el hueco, así que las balas pasan.
* Los pocos lugares así que tiene dust2 cambian igual.

Comprobado en la prueba de caminar: con altura de jugador agachado se llega del lado de las piedras al agujero, y del agujero se baja a B. Desde B no se sube (está 3,6 m arriba), igual que en CS.

### Las piedras
En CS no se puede subir una cara más empinada que unos 45° (normal con z < 0,7): uno resbala. El juego, en cambio, toma como piso cualquier cara del `.hm` con y ≥ 0,3 (hasta unos 72°). Así uno trepaba caras de roca que en CS son paredes y quedaba metido en grietas entre piedras.

Ahora cada cara de ese rango (0,3 a 0,7) con más de un escalón de alto lleva una **caja de colisión desde su pie hasta su parte de arriba**, que choca como una pared. En dust2 son 104 cajas. También tapan el costado inclinado del agujero, que de otro modo dejaba entrar al interior de la pared.

### Los cuatro mapas
`mp_do_dust2`, `mp_dmt_aim_map`, `mp_dm_pool_day` y `mp_dmt_pool_day` están rehechos con esto y con tus escenas.
* dust2 lleva su DLL de §90: volar A y B, zonas en el HUD, 40 s y espera a la bomba.
* Prueba de caminar con escalón de 20 cm:
  * dust2 llega a A, a B y a la base contraria con las mismas distancias que antes;
  * en aim_map y en las dos pool_day se llega a todos los botiquines y nacimientos.

**No probado en el juego.**

## 92. Destruir el objetivo: el minimapa señala la zona más cercana que sigue en pie

El minimapa (`mp_Radar`) del DO común siempre señala `bombZone` (A): la DLL del juego lo fija una sola vez, al armar la escena, con `Radar::SetTargetName(0, "bombZone")`.

Casilla nueva: **"el minimapa señala la zona de bomba más cercana que sigue en pie"** (tildada por defecto).
* En cada cuadro de la ronda, el código de las zonas (§90) toma la posición del jugador local (`CGame::mainCharacter`), mide la distancia a cada zona que todavía no explotó y apunta el minimapa a la más cercana.
* Solo llama a `SetTargetName` cuando cambia la zona. Si ya no queda ninguna, usa `ClearTarget`.
* Cada máquina lo calcula para su propio jugador.
* Con el modo "todas las zonas": si estás más cerca de B y B sigue en pie, el minimapa señala B; cuando B explota, pasa a A.
* No se aplica a plaza ni a asalto, que manejan su propio minimapa.

Se probó ejecutando el código con el juego simulado (`tools/asm/harness.c`):
* sin jugador local no hace nada;
* cerca de B señala B;
* no se llama en cada cuadro;
* con B destruida pasa a la más cercana que queda;
* con todas destruidas limpia el minimapa;
* en una escena nueva vuelve a fijarlo;
* deja en paz plaza y asalto, y se apaga con la casilla.

`mp_do_dust2.zip` trae la DLL rehecha con esto. El mapa y la escena no cambian respecto de la entrega anterior. **No probado en el juego.**

## 93. "new_map_from_cs failed: No module named 'scipy'" (fy_nuketown)

**Qué pasaba.** Dos partes del importador usaban `scipy`, que no está en `requirements.txt` ni en tu Python:
* el cierre de agujeros chicos en el piso (§89);
* el borrado de caras de afuera de los `.rmf`.

En esta PC de pruebas estaba instalado, por eso no saltó. Además, como el error llegaba después de copiar la escena modelo con el nombre nuevo, quedaba un `mp_dmt_nuketown` que en realidad era Madrid.

**Arreglo:**
* `vtoy/ndi.py` hace en numpy puro lo poco que se usaba de `scipy.ndimage`:
  * piezas conectadas (`label`, `find_objects`);
  * crecer una máscara (`binary_dilation`);
  * el cierre de alturas (`grey_closing`);
  * "angosto en todas partes" (`narrow`).

  El importador ya no necesita `scipy`. Un test compara `ndi` con `scipy` donde está instalado; otro corre el importador con `scipy` bloqueado.
* Si "Crear un mapa nuevo desde .bsp / .rmf" falla a mitad de camino, borra los archivos que había creado con el nombre nuevo y vuelve a cargar la escena modelo.
* Los botiquines del mapa nuevo se ponen entre los nacimientos y el centro de cada base, **en el mismo piso que los nacimientos**. En fy_nuketown, uno caía adentro de una casa, debajo del techo.

**fy_nuketown** (con tus `.wad`):
* 98 de 98 texturas;
* 30 nacimientos (15 y 15);
* 6 botiquines;
* la prueba de caminar llega a todos;
* la revisión del mapa no encuentra problemas.

Va `mp_dmt_nuketown.zip` armado así. **No probado en el juego.**

## 94. de_aztec_go -> mp_do_aztec_go; texturas "{" sin borde azul

**El mapa.** Se convirtió con **Crear desde .bsp / .rmf**, modo DO:
* las 46 texturas vienen adentro del `.bsp`, así que no hace falta ningún `.wad`;
* 32 nacimientos (16 y 16);
* las dos `func_bomb_target` pasan a ser `bombZone` (A) y `bombZone_B`;
* la copia de la DLL de DO cuenta las dos zonas, con los íconos en el HUD y el minimapa que señala la zona más cercana;
* como en el juego, volar cualquiera de las dos gana la ronda.

Prueba de caminar con escalón de 20 cm:
* desde los nacimientos se llega a A (127 m), a B (106 m) y a la base contraria;
* se llega a los 6 botiquines;
* no hay agujeros en el piso a 15 m de las zonas;
* la revisión del mapa no encuentra problemas.

**Texturas "{" (enredaderas, plantas, rejas).** En Half-Life los píxeles transparentes de esas texturas son azules. Al achicarlas a medida potencia de 2, o al filtrarlas, ese azul se mezclaba en los bordes de las hojas. Ahora, antes de achicarlas, los píxeles transparentes toman el color de los visibles más cercanos (`_bleed_colours`), así que en los bordes no aparece azul.

**No probado en el juego.**

## 95. de_aztec -> mp_do_aztec; caras que dan al cielo

**El mapa.** Se convirtió con **Crear desde .bsp / .rmf**, modo DO:
* las 38 texturas vienen adentro del `.bsp` (lista 13 `.wad`, pero no hace falta ninguno);
* 32 nacimientos (16 y 16);
* `bombZone` (A) y `bombZone_B`, con los íconos en el HUD y el minimapa que señala la zona más cercana;
* como en el juego, volar cualquiera de las dos gana la ronda.

Prueba de caminar con escalón de 20 cm:
* desde los nacimientos se llega a A (109 m), a B (130 m), a la base contraria y a los 6 botiquines;
* cerca de las zonas, los dos lugares sin piso que marca la revisión son el interior de paredes y columnas (sólido en el mapa de CS, nadie entra);
* la revisión del mapa no encuentra problemas.

**Caras que dan al cielo.** de_aztec tiene "techos de cielo": bloques con la cara de abajo de cielo y la de arriba con la textura `barrel2b` (verde oliva).
* En CS esa cara de arriba no se ve nunca, porque queda adentro del bloque de cielo de encima.
* El importador la dibujaba igual, y en el mapa quedaban planchas oliva sobre las calles.

Ahora el importador le pregunta al árbol del propio mapa (hull 0) qué hay delante de cada cara del mundo. Las que dan a un bloque de cielo o a sólido, que CS nunca muestra, ya no se dibujan.
* de_aztec: 220 caras menos;
* de_aztec_go: 25;
* de_dust2: 164 (el dust2 ya entregado no se rehízo: esas caras no se ven desde adentro del mapa).

`mp_do_aztec_go.zip` va rehecho con esto. **No probado en el juego.**

## 96. mp_do_dust2_cs2, mp_do_mirage_cs2, mp_dmt_rifle_india

Convertidos con **Crear desde .bsp / .rmf**.
* Los `.rar` se abrieron con la libarchive del sistema.
* Las texturas vienen todas dentro de cada `.bsp` (dust2_cs2: 159, mirage_cs2: 171, india: 16), así que no hizo falta ningún `.wad`.
* Los nacimientos siguen la regla de siempre: `info_player_start` (CT) es el equipo 0 e `info_player_deathmatch` (T) el equipo 1, 16 de cada lado.
* En DO, las dos `func_bomb_target` son `bombZone` (A) y `bombZone_B`. La copia de la DLL trae los íconos en el HUD y el minimapa que señala la zona más cercana; volar cualquiera gana la ronda.

| mapa | modo | caminando (escalón 20 cm) |
|---|---|---|
| mp_do_dust2_cs2 | DO | A 139 m, B 113 m, base contraria 117 m; 6 botiquines; sin agujeros a 15 m de las zonas |
| mp_do_mirage_cs2 | DO | A 79 m, B 118 m, base contraria 120 m; 6 botiquines; sin agujeros a 15 m de las zonas |
| mp_dmt_rifle_india | DMT | se llega a los 6 botiquines y a los 32 nacimientos |

**Lo que no se trae: los modelos `.mdl`.**
* Son autos, combis, palmeras, toldos, bolsas de basura, macetas y carros: 88 en dust2_cs2 (13 modelos distintos) y 86 en mirage_cs2 (17).
* El importador lee los bloques del mapa, no los modelos de Half-Life. Esas cosas no aparecen.
* Tampoco chocan, salvo donde el autor del mapa puso bloques "clip" alrededor, que sí se importan como colisión.

En mirage_cs2:
* las 2 escaleras de mano (`func_ladder`) no se pueden trepar, porque el juego no tiene escaleras de mano;
* las 17 `func_breakable` (vidrios, cajas) quedan fijas.

**No probado en el juego.**

## 97. Modelos sueltos de los mapas de CS (.mdl): autos, palmeras, toldos...

Lo que el mapa pone con `cycler`, `cycler_sprite`, `env_model`, etc. con un `.mdl` ahora se importa.

**`vtoy/mdl.py`** lee los modelos de Half-Life (versión 10):
* las texturas propias (8 bits con paleta; las "masked" con transparencia), o las del `...T.mdl` cuando van aparte;
* la tabla de skins y los grupos de cuerpo (`body`, `skin` de la entidad);
* los huesos en la primera pose (secuencia 0, cuadro 0);
* las tiras y abanicos de triángulos.

**Dónde busca los modelos** (`models/de_mirage_cs2/van.mdl`): en la carpeta de arriba de la carpeta `maps` del mapa (`cstrike/`), junto al mapa y junto a los `.wad` cargados. Si el nombre difiere solo en mayúsculas, también lo encuentra. En **Crear desde .bsp / .rmf** se ve cuántos modelos encontró y cuántos faltan; el cartel dice dónde ponerlos.

**Cómo los pone:**
* Cada modelo va donde dice la entidad (origen y ángulos), con sus texturas convertidas en texturas nuevas del juego. Una misma imagen usada por dos modelos se escribe una sola vez.
* Los "cielos" (domos de nubes de más de 6000 unidades, como el `env.mdl` de dust2_cs2) no se traen: el juego tiene su propio cielo.
* **Colisión:** una caja alrededor de la parte de abajo (hasta 64 unidades) solo para los que **apoyan en el piso** (el árbol del mapa dice que debajo hay sólido) y **no son de textura calada**.
  * Tienen caja: autos, combis, el blindado, macetas, canastas, bancos, sillones, bolsas.
  * Se atraviesan, como en CS: palmeras, helechos, ramas, toldos colgados y la escenografía grande del fondo.

**Los dos mapas, rehechos:**
* `mp_do_dust2_cs2`: 54 modelos, 19 con caja;
* `mp_do_mirage_cs2`: 54 modelos, 9 con caja.

La prueba de caminar da lo mismo que antes: A, B, la base contraria y los botiquines con las mismas distancias. `props_check.png` muestra algunos de cerca (la combi, el auto, las palmeras). **No probado en el juego.**

## 98. mp_do_washingtonpark (Syphon Filter) y lluvia en el modo bomba (DO)

### El mapa
`mp_do_washingtonpark`: Washington Park de Syphon Filter, armado a partir del plano de la misión y del video. Es de noche, con lluvia y niebla.

Va de sur a norte:
* **Entrada:** la calle con su vereda. Ahí nacen los **T** (equipo 1, atacantes, 16 lugares) y está la bomba.
* **Sendero de entrada:** entre paredes de ladrillo, sube a la **plaza de la estatua** (pedestal, maceteros con seto, bancos, faroles).
* **Jardín del oeste:** sale de la plaza hacia el oeste y sube por un sendero entre setos altos. Después vuelve al centro.
* **Sendero central:** sube hacia el norte. Al este salen las **canchas de tenis**: cerco de alambre, líneas, red baja que sirve de cobertura.
* **Laberinto de setos:** varios caminos posibles.
* **Memorial:** escalones, plataforma y bloques grandes de piedra. Ahí nacen los **CT** (equipo 0, defensores, 16 lugares).

Hay árboles (el tronco es sólido; la copa se atraviesa) y faroles en los senderos.

**Objetivos:** tres zonas de bomba.
* `bombZone`: A, la estatua.
* `bombZone_B`: B, el jardín del oeste.
* `bombZone_C`: C, las canchas de tenis.

**Reglas**, las mismas que tu `mp_DestroyTheTargetCS.dll`:
* hay que volar **todas** antes de que se acabe el tiempo;
* hay iconos en el HUD;
* el minimapa señala la zona más cercana en pie;
* la bomba explota a los **40 s**;
* a las **0:00**, si hay una bomba puesta, el reloj muestra los segundos que le faltan;
* hay 3 bombas para levantar (una por zona).

**Clima:** la lluvia de Marbella, más el cielo y la niebla de Marbella. La escena parte de `mp_do_marb`.

Todo eso va en una sola copia nueva: `mp_DestroyTheTarget_mp_do_washingtonpark.dll`. No se reemplaza ninguna DLL del juego ni tu `mp_DestroyTheTargetCS.dll`.

Las texturas son todas del juego: césped, seto del laberinto, vereda, ladrillo, piedra, asfalto y alambrado del estadio.

### Lluvia en el modo bomba (sección DO del editor)
**Por qué hacía falta código nuevo.** Las DLL de DO del juego (`mp_DestroyTheTarget`, `mp_DestroyTheMArb`, etc.) **no tienen lluvia**: no importan `AddShower`. Por eso *Weather ▸ Make rain DLL* (que cambia el nombre del mapa que compara la DLL de DM/CTF) no sirve para DO.

**Qué hace la copia.** Repite exactamente lo que hace `mp_deathMatch` en Marbella:
* **al empezar la escena:** `AddShower(escena, (0, 5000, 0), 30000, 30000, (0, -1500, 0))`, guardada en el juego (`CGame +0x1334`), igual que el juego;
* **al terminar la escena:** `RemoveRenderObject` sobre la lluvia, para que no siga en el mapa siguiente.

**Cómo está hecha la copia:**
* Esas funciones de `vtKernel` entran como una **importación nueva** de la copia: se agrega una entrada a la tabla de importaciones, dentro de la sección `.vtoyz`. La tabla original queda intacta.
* Opción **rayos**: `ShowerSetIlumRayo(lluvia, 1)`, lo que hacen los mapas de la iglesia al aire libre. Marbella no tiene rayos, así que viene destildada.

**En el editor**, sección *Destroy the target*, bloque **Rain (storm) in this DO map**:
* casillas *rain like Marbella* y *lightning*;
* botón **Apply the rain to this map**.

**Compatibilidad: se suma, no pisa nada.** La lluvia va en la misma copia que las zonas (todas / cualquiera), el HUD, el minimapa y la bomba (segundos y espera a las 0:00):
* Aplicar la lluvia mantiene todo eso.
* Volver a aplicar zonas o bomba mantiene la lluvia.
* Sacar la lluvia deja la DLL igual a como sería sin ella: la tabla de importaciones y el final de la escena vuelven a ser los del juego.

Sirve aunque el mapa tenga una sola zona: en ese caso la prueba de la zona del juego no se toca.

Para el cielo oscuro: *Weather ▸ Storm look*.

**Lo que no está:** las salpicaduras de gotas en el piso alrededor del jugador (`gota_salpica`), que `mp_deathMatch` dibuja en cada cuadro. Solo está la lluvia en sí.

**Pruebas:**
* El código nuevo se corrió nativo en el arnés (`tools/asm/harness.c`) con el juego simulado: argumentos de Marbella, guardado en `+0x1334`, borrado al final una sola vez, rayos, y las dos líneas originales del final de la escena.
* Tests de las tablas: importaciones nuevas, saltos y restauración.

**No probado en el juego.**

## 99. mp_do_dust2_cs2 y mp_do_mirage_cs2 no iniciaban; salpicaduras de lluvia en DO

### Los dos mapas, rehechos
No tengo el juego para ver el error, así que comparé los dos mapas contra todos los del juego y contra los mapas nuestros que sí andan (`mp_do_dust2`, `mp_do_aztec`). Estos dos eran los únicos fuera de lo que el juego usa en cuatro cosas, y las cuatro se corrigen al importar.

**1. Nombres de textura largos.**
* *Antes:* `dust_vehicle_glass_opaque_color.tex` tiene 35 letras y `datepalm_fronds_01_saturated.tex` tiene 32. Llegaron con los modelos `.mdl` de §97.
* *En el juego:* ningún mapa usa un nombre de textura de más de **31 letras con ".tex"**.
* *Ahora:* las texturas nuevas se cortan a 27 letras más ".tex". Si dos nombres quedan iguales, el segundo lleva un número.

**2. Mallas gigantes.**
* *Antes:* el importador hacía una malla por textura con todo el mapa adentro, de hasta 14.121 vértices.
* *En el juego:* la malla más grande tiene 1.427 vértices. En `mp_do_dust2`, que anda, llegaba a 5.475.
* *Ahora:* cada textura se corta por cuadrados de 30 m del mapa, con 600 caras como máximo por malla:
  * dust2_cs2: 832 mallas, la más grande de 1.800 vértices;
  * mirage_cs2: 869 mallas, la más grande de 2.965 vértices.
  * El máximo de mallas en un mapa del juego es 971.

**3. Sectores.** Los sectores son lo que el juego mira para saber qué dibujar y contra qué chocar en cada lugar.
* *Antes:* 64 hojas de unos 23 m. En mirage, una hoja tenía **1.139** cajas de colisión y 94 mallas.
* *En el juego:* como mucho, 174 cajas y 54 mallas por hoja.
* *Ahora:* hojas de unos 6 m (1.024 hojas), y cada malla aparece solo donde está:
  * dust2_cs2: hasta 189 cajas y 43 mallas por hoja;
  * mirage_cs2: hasta 263 cajas y 56 mallas por hoja (tiene 16.305 cajas en total).

**4. Lo que se dibuja a la vez.** Como cada malla está ahora en su lugar, el juego ya no dibuja el mapa entero en cada cuadro.

Las texturas, la colisión, los nacimientos (T y CT), las zonas A y B, los botiquines y los modelos son los mismos de antes.

### Opción nueva: salpicaduras de las gotas en el piso (modo DO con lluvia)
Bloque *Rain (storm) in this DO map*: casilla **drops splash on the floor round the player (like Marbella)**.

Hace lo mismo que `mp_deathMatch` en Marbella, en cada cuadro:
1. Calcula un cuadrado de 4000 × 4000 a 2000 unidades por delante de la cámara.
2. Elige *intensidad de la lluvia × 20* puntos al azar dentro de ese cuadrado.
3. En cada punto busca el piso (`GetHeight`).
4. Donde hay piso pone una salpicadura corta: `AddParticleSystem` con `gota_salpica.tex`, con los mismos 20 valores que usa Marbella, y `SetParticleCountDown(…, 7)`.

**Cómo está hecho:**
* Hay un enganche nuevo al principio del `Run` de la escena. Toma las 4 instrucciones `push` y las 2 líneas que reemplaza, y conserva los indicadores de la comparación que el juego hace justo antes.
* Las funciones nuevas (`CameraGetViewMatrix`, `GetColumn`, `CameraGetPosition`, `ShowerGetIntensidad`, `Random`, `GetHeight`, `AddParticleSystem`, `SetParticleCountDown`) entran en la misma importación nueva de la lluvia.
* La sección `.vtoyz` pasa a 8 KB.
* Si una copia hecha antes tenía la sección chica, se rehace sola.

**Cuándo no hace nada:**
* sin lluvia;
* sin jugador local (el servidor);
* sin cámara.

**Compatibilidad:** se suma a lo demás, igual que la lluvia. No cambia las zonas, el HUD, el minimapa ni la bomba de 40 s con la espera a las 0:00. Si se saca, la DLL vuelve a ser la de antes.

Washington Park sigue **sin** salpicaduras, como pediste.

**Pruebas:** el código se corrió nativo en el arnés, con el juego simulado. Se comprobó:
* las líneas que reemplaza y los indicadores;
* la cantidad de gotas;
* el cuadrado delante de la cámara;
* los 20 argumentos;
* los casos sin lluvia, sin cámara y sin jugador.

**No probado en el juego.**

## 100. Armas por mapa en DMT / DM, mirage_cs2 (chapa de jungla, paredes invisibles) y revisión en Help ▸ About

### "weapons DLL failed: … unknown mode DLL" (mp_dmt_rifle_india)
**El problema.** Elegir las armas por mapa (por ejemplo, cuchillo y rifle) solo funcionaba con las DLL de capturar la bandera. Además, el cartel amarillo decía que no encontraba la DLL, cuando en realidad la encontraba pero no la sabía leer.

**Por qué.** Las DLL de deathmatch reparten las armas igual que las de bandera, pero con otros registros. Además, las balas de los grupos 3, 4 y 5 salen de una tabla propia de la DLL, y esa tabla se lee dos veces: al crear al jugador y al renacer.

**Qué cambié.** El editor ahora reconoce las dos formas de deathmatch:
* `mp_deathMatchTeam` y `mp_deathMatchChalet`: reparten las armas al crear al jugador y al renacer.
* `mp_deathMatch` y `mp_deathMarb`: reparten las armas en un solo lugar, cada vez que el jugador nace.

En las dos funciona lo mismo que en bandera:
* sacar grupos;
* fijar un arma;
* dejar varias armas de un grupo;
* volver a todas las armas.

Con un arma fija, las dos tablas de balas usan esa arma: el rifle recibe las balas del rifle aunque el jugador haya elegido la uzi en el menú.

Con todas las armas otra vez, la DLL queda igual a la del juego.

El cartel ahora distingue dos casos: la DLL no se encontró, o se encontró pero no se puede leer.

**Lo que no funciona todavía.** Las DLL de destruir el objetivo (DO) siguen sin poder elegir armas, porque mezclan el reparto con la bomba y el kit. Ahora el editor lo dice en lugar de pedir la DLL.

### mp_do_mirage_cs2
* **Paneles rompibles.** Son los `func_breakable` finos: la chapa, las tablas o el vidrio que tapan un agujero o una ventana. En CS se abren de un tiro; en Torrente quedarían para siempre. Ahora no se importan, así que el agujero queda abierto.
  * En mirage son 3:
    * la **chapa de la ventanita a ras del piso** (se pasa agachado);
    * la chapa de la ventana alta;
    * las tablas.
  * Las macetas rompibles (cajas de 26 × 26) se quedan.
* **Paredes invisibles.** Son entidades con *render amount* 0, como `nowallshot` y `babfl`. Antes se dibujaban semitransparentes y en el editor se veían como manchas azuladas sin textura. Ahora no se dibujan, pero siguen bloqueando como en CS.
* **Caras con la textura `{invis`.** En CS no se ven. Ahora tampoco se dibujan.
* **Agujeros en los techos.** Los "huecos" que se ven desde arriba con la cámara libre son techos que el mapa de CS no tiene: encima hay un bloque de cielo y CS no los dibuja. Desde la calle se ve el cielo, igual que en CS.
* **Ventanas abiertas.** Probé quitar la colisión de las paredes invisibles de las ventanas de forma automática. Con las vistas comprobé que también agarraba estantes, puertas falsas y nichos, así que lo saqué. Para una ventana puntual que siga bloqueando:
  * herramienta *Pen ▸ Delete collision inside outline*;
  * o decime dónde está y la abro.

### Help ▸ About
Debajo del link de GitHub, en amarillo: **rev v1.0.0 - fecha y hora** de esta entrega. Cada entrega del editor suma 1 al último número (v1.0.1, v1.0.2…). Está en `vtoy/__init__.py` (`APP_REV`, `APP_REV_DATE`).

**No probado en el juego.**

## 101. rifle_india: el hueco arriba de las puertas

### Qué pasaba
Los arcos de las puertas de awp_india están hechos de varias piezas. Algunas caras de esas piezas tocan, en el centro, otra pieza del arco. El filtro de §95 decidía si dibujar una cara mirando **un solo punto**, delante de su centro:
* si ese punto caía en sólido, la cara no se dibujaba;
* pero el resto de la cara sí se veía en CS.

Por eso quedaba un hueco entre la puerta y el arco, y a través de él se veía el cielo.

### Qué cambié en el importador
* Ahora se mira el centro **y cerca de cada esquina** de la cara.
* Solo se deja de dibujar una cara si **toda** ella da contra un bloque de **cielo**: el techo olivo de aztec (§95), que es lo que buscaba ese filtro.
* Una cara que solo toca sólido queda enterrada y se dibuja igual. No se ve y no deja grietas.

### Tu mapa
Arreglé el mapa que me mandaste, con tus cambios:
* La escena y tu DLL de armas (`mp_deathMatchTeamRifleIndia.dll`, cuchillo y rifle) quedan iguales, byte por byte.
* La colisión y el mapa de alturas no cambian.
* Se agregaron las 26 caras de arco que faltaban, en una malla nueva con la textura `in_24`, en el mismo lugar del mapa.
* Los sectores se rehicieron con hojas de unos 5 m.

En el zip va solo tu DLL de armas. El tuyo traía también copias de `mp_CameraStartPosition.dll`, `mp_CStartPoint.dll` y `mp_salud.dll`, que son idénticas a las del juego.

Revisé las 10 puertas en vistas de antes y después: en todas el hueco desapareció.

**No probado en el juego.**

## 102. Botiquines: tiempo para volver a aparecer, por mapa

### Cómo funciona en el juego
En `mp_salud.dll`:
* al levantar un botiquín, el botiquín se esconde y guarda la hora (`GetTime`, en ms);
* en cada cuadro, si pasaron más de **5000 ms**, vuelve a mostrarse.

Son **5 s** para el grande y para el chico, en todos los mapas. Lo que da cada uno (50 / 25) sí es del botiquín de la escena, y la vida nunca pasa de 100.

### En el editor
*Game mode / sky / spawns / music ▸ Health packs: time to come back*:
* muestra cuántos botiquines hay, el tiempo actual y la DLL que usan;
* **Apply to this map** hace una copia `mp_salud@<mapa>.dll` con el tiempo elegido (de 1 a 600 s), y los botiquines de la escena pasan a usarla;
* **Game's time (5 s)** vuelve a la DLL del juego.

**Cómo es la copia:**
* Se cambia un solo número: la constante de 5000 que la DLL lee en un único lugar.
* La DLL del juego no se toca.
* *Export this map as .zip* incluye la copia en `dll/`. Hay que ponerla junto a las demás DLL del juego, en el servidor y en la PC de cada jugador.

**No probado en el juego.**

## 103. Los cuadrados negros de aztec y lluvia sin tormenta

### Cuadrados negros (`black.tex`)
En de_aztec, los huecos entre cajas y algunos rincones usan la textura `black` de CS. En Torrente se ven como cuadrados negros.

**Por qué no conviene borrar esa malla.** Al borrar una malla, el editor también borra la colisión que hay dentro de su volumen, y por eso se iban escaleras y paredes.

**Herramienta nueva.** En *Textures: search / replace* está **Use the textures around it** (por defecto, `black.tex`).
* Cada cara negra toma la textura de las caras con las que comparte un borde, la más común. Si no toca ninguna, toma la de la cara más cercana.
* Si la vecina está en el mismo plano, sigue su mismo mapeo y la textura continúa sin corte. Si no, usa la escala de esa textura.
* **Solo cambia el dibujo:** la colisión y el mapa de alturas quedan idénticos (lo comprueba el test).

**mp_do_aztec (sobre el que te entregué):** las 60 caras negras quedaron con las texturas de alrededor:
* las caras de las cajas (`AzStatA/B/C`);
* el piso;
* la piedra y el musgo.

La comparación antes y después está en `mp_do_aztec_black.png`.

**Otros mapas con `black.tex`:** dust2_cs2, mirage_cs2 y nuketown. Ahí no lo apliqué, porque en algún caso puede ser negro a propósito (un interior oscuro). Si lo querés, es un botón.

### Lluvia sin tormenta
La lluvia de Marbella es el objeto `vtShower` de `vtKernel`, y la tormenta viene incluida:
* **relámpagos:** mientras su indicador +0xE8 esté prendido, que viene prendido;
* **truenos:** seis sonidos (`trueno.wav`, `trueno_2/3`, `trueno bajo_1/2/3`), en +0xB4…+0xC8.

`AddShower` devuelve el objeto mismo. Así, la copia DO puede, justo después de crearlo:
* apagar los relámpagos;
* vaciar los seis sonidos de trueno. Cada lugar que los usa salta un sonido vacío, y al cerrar la escena también se omiten.

El sonido de la lluvia (`LLUVIA_2.wav`) queda.

**En el editor**, sección DO, bloque *Rain*: la casilla **storm: thunder and lightning flashes (like Marbella)**.
* Tildada (como venía): tormenta, igual que Marbella.
* Destildada: **lluvia tranquila**.

**Lo que cambia respecto de antes:**
* Reemplaza a la casilla anterior de "lightning". Esa casilla no hacía falta: el relámpago ya viene prendido.
* Las copias hechas antes (Washington Park) siguen siendo con tormenta.

**Probado con el arnés:**
* con tormenta, el objeto queda intacto;
* sin tormenta, el indicador y los seis sonidos quedan en 0 y el de la lluvia queda.

**No probado en el juego.**

## 104. Paredes grises en dust2_cs2 y mirage_cs2: la luz del mapa de CS (lightmaps)
**Qué pasaba.** No faltaba ninguna textura: las 175 y 184 texturas del mapa están en el zip y se cargan. Pero en estos mapas de CS2 pasados a CS 1.6, muchas texturas son grises:
* `dust_brick01`: color medio (131, 127, 122), casi sin contraste;
* `dust_wall01`, `dust_wall03`, `dust_bote05`, etc.

En CS, el color tostado y las sombras los pone la **luz del mapa**: cada pared se dibuja como *textura × lightmap* (sol cálido, ambiente azulado, sombras). El juego no tenía esa luz, así que esas paredes quedaban grises y planas, como en el video.

**Lo que hace ahora.** El juego ya sabe dibujar un material con **dos texturas**: la segunda multiplicada ×2 (`MODULATE2X` en la etapa 1 de `vtKernel`). Es lo que usan sus propios mapas con las texturas `glow_*` / `Grad_*`. El editor:
1. lee los lightmaps del `.bsp` (estilo 0 de cada cara);
2. los acomoda en páginas de 512×512, con cada cara alineada a los bloques DXT para que no se mezclen colores;
3. las guarda como texturas nuevas `<mapa>_lm0.tex`, `_lm1`… Nunca pisan una del juego;
4. le da a cada malla hecha desde el `.bsp` esa segunda textura y segundas coordenadas (vértice tipo 1, como los del juego).

**Brillo:**
* 128 deja la textura igual;
* la luz de sol típica queda en ~140 (un poco más clara y cálida);
* las sombras, más oscuras.

Los triángulos que no salen de una cara del `.bsp` (autos, palmeras, mallas propias) reciben la luz típica del mapa.

**No cambia:** las colisiones, el height map ni la cantidad de mallas.

**En el editor:**
* **Importar .bsp** y **Create from .bsp**: casilla nueva *its light: sun, shadows, lamps*, tildada por defecto.
* **Textures**: *the .bsp this map was made from* + **Add the light of the .bsp (sun, shadows)**, para un mapa ya hecho. Dónde quedó apoyado el mapa lo encuentra solo, comparando sus paredes con las del `.bsp`.

**Los mapas del usuario** (con sus cambios):
* `mp_do_dust2_cs2.zip`: 687 mallas con luz, 14 texturas de luz;
* `mp_do_mirage_cs2.zip`: 696 mallas con luz, 13 texturas de luz.

**Prueba nueva:** una arena con lightmaps (piso claro, paredes oscuras). Comprueba:
* las mallas importadas toman la luz;
* las del mapa no se tocan;
* las colisiones quedan igual;
* en un mapa importado sin luz, la ubicación se encuentra sola y la luz se agrega una sola vez.

**No probado en el juego.**

## 105. Bomba en 0:00, HUD de DO, cierre al salir, agua de aztec, clima en todos los modos, luz de CS, autos, HD, About
**Versión:** el About muestra ahora `versión - rev fecha hora` (ahora `v1.0.5 - rev 21/11/2026 09:28`), el enlace `https://github.com/Lahrenheit/VToyEditorPlus` y, debajo del título, "Based on Patoke's VToyEditor". También se actualizó `version_info.txt`.

### La bomba que explota en 0:00 y gana el rojo
En el video, la bomba se plantó en 0:08. El reloj pasó a 0:33 (el tiempo que le quedaba a la bomba más 2 s), pero la explosión llegó recién en 0:00, junto con el "fuera de tiempo", y ganó el rojo.

Lo que fallaba:
* la explosión llega desde el servidor con un poco de demora;
* la bomba que explota sale enseguida de la lista de bombas de la escena. Por eso el control "una bomba que explotó hace un momento" no la encontraba.

**Arreglo** (código de la bomba, versión 2):
* el Run de la escena anota cuándo vio por última vez una bomba activa o explotando, aunque después salga de la lista;
* en 0:00 se esperan 3 s más si eso pasó hace menos de 6 s, y la ronda la gana la explosión;
* el reloj muestra ahora el tiempo de la bomba más 3 s (antes, más 2).

Un arnés nuevo (`tools/asm/otharness.c`) corre ese código de verdad (32 bits) con el juego simulado:
* el tiempo de plantado se corre una sola vez;
* 0:00 con la bomba activa;
* la bomba atrasada;
* la bomba que explotó y salió de la lista;
* ninguna bomba.

**Ojo con "ALL must be blown up":** las copias `mp_DestroyTheTargetCS*` de dust2 y mirage tienen esa casilla tildada. Con ella, volar una sola zona no gana: hay que volarlas todas antes de 0:00. Para jugar como en CS 1.6 (cualquier zona gana), hay que destildarla.

### El HUD de DO que quedaba en otros mapas, y el cierre del juego al salir
Los iconos de objetivos que agrega la copia DO (AddSprite) nunca se sacaban:
* quedaban en pantalla en el mapa siguiente;
* como la escena se rehace en cada ronda (`__ReStart__` → `Reset`), se juntaban de a 4 por ronda.

Ahora el final de la escena los saca con `RemoveRenderObject`, como hace el juego con sus propios iconos en ese mismo lugar. Para la cantidad de iconos se usa una variable nueva (`V_NSPR`).

Creo que la acumulación de iconos también explica el cierre del juego al salir después de jugar mucho ese mapa: sprites viejos apuntando a texturas ya liberadas. No lo pude comprobar.

Además, la lluvia tranquila ahora libera (`ReleaseSound`) los seis truenos en lugar de solo vaciarlos. Antes se perdían seis sonidos por ronda.

**En el editor:** si la DLL del mapa la hizo un editor anterior, la sección DO lo avisa en amarillo y ofrece **Update the map's DLL**, que la rehace con todo lo que tenía.

### El agua que parpadea (aztec)
El `func_water` de CS traía todas sus caras:
* la superficie, vista de arriba y de abajo;
* el fondo, apoyado en el piso de la pileta (el mismo plano: parpadea);
* los costados bajo el agua.

Cambios:
* **Textures > Water that flickers in the game**: deja solo la superficie, con el material de dos caras. En aztec pasa de 830 triángulos a 67. La colisión no cambia.
* **Al importar un .bsp**: el agua ya viene solo con su superficie.

### Clima en todos los modos (Gameplay > Weather)
Sección nueva en *Map tools > Gameplay*. Tiene:
* lluvia;
* tormenta (truenos y relámpagos) o lluvia tranquila;
* salpicaduras (solo DO);
* **volumen de los truenos** y **de la lluvia**, de 0 a 100 %.

Cómo funciona en cada modo:
* **DO:** igual que antes, la copia de la DLL de DO (mantiene zonas y tiempo de bomba).
* **DM / DMT / banderas:**
  * una copia de la DLL del modo que llueve en ESTE mapa (`patch_map_name`, ahora con la marca `VTOYMAP`);
  * más una sección `.vtoyw` (`tools/asm/weather.s`) cuyo único `call [AddShower]` pasa por un stub;
  * ese stub llama a `AddShower` y después a `fix_shower` (`tools/asm/shower.inc`, que también usa la copia DO).
* **Las armas elegidas para el mapa se mantienen**, y "Weapons" mantiene la lluvia.

**Volumen:**
* El juego pone el volumen de cada trueno justo antes de sonarlo (intensidad × 7 + 0,3), así que no se puede bajar desde la DLL.
* En su lugar, el editor hace copias más bajas de los wav del juego, solo para el mapa (`wavs/<mapa>_<vol>_trueno.wav`…; PCM 8/16/24/32 bits o float).
* `fix_shower` libera el sonido del juego y carga la copia (`LoadSound`, igual que lo hace vtShower).
* Las copias van en el zip del mapa y el instalador nunca reemplaza un archivo distinto. Los sonidos del juego y los otros mapas no cambian.

El bloque de lluvia que estaba en la sección DO pasó a esta sección. *Weather* (Look y el panel principal) quedó con el cielo de tormenta y la luna.

### La luz de CS: modelos, vista en el editor, guardar con o sin
* **Modelos** (autos, palmeras, macetas, cajas): toman la luz del piso que tienen debajo, como en CS. Un mesh que es todo modelo recibe una sola luz; un mesh del mapa con algunos triángulos sueltos, una por triángulo. Antes recibían una luz "típica" o quedaban sin luz.
* **Color:** el tono ahora aplica la gamma a cada color por separado, como la gamma de luz de CS. El sol naranja de mirage queda cálido, no anaranjado.
* **Editor:**
  * la vista dibuja la segunda textura ×2, como el juego (atributo 3, `uTexture1` / `uUseLM` en el shader);
  * casilla *show the CS light in the editor*;
  * **Take the CS light off** deja el mapa como antes (`lightmap.strip`), y *Add the light* la vuelve a poner;
  * el mapa se guarda como se ve;
  * el `.bsp` usado queda recordado por mapa.

### Autos indestructibles con la forma del auto, y la vuelta
* **Make it indestructible:** las cajas de colisión siguen el perfil del auto (`meshbox.profile_boxes`: 16 cortes a lo largo, unidos cuando son parecidos). Capó y baúl quedan bajos y la cabina alta, así se ve y se dispara por encima de las partes bajas. Son de 3 a 6 cajas según el modelo.
* **Make it a car that can be blown up again:** vuelve a `mp_CCar` y saca las cajas de adentro del auto. También existe para todos los autos de decorado del mapa.

### HD
* **Mesh o prop seleccionado** que cambia con la distancia: **HD: full detail at any distance (this one)**. Con **back to the game's far versions** vuelve a como estaba.
* **Módulos con modelo `_hd`:** muestran "HD" y **back to the game's model**.

**Probado:** con pruebas nuevas y arneses de 32 bits. **No probado en el juego.**

## 106. mp_do_mirage_cs2: paredes transparentes en el mercado (y huecos en dust2_cs2)
**El problema.** En el mercado faltaban las paredes de yeso de atrás de los estantes (`plaster_int02`), estantes `{pve_Hshelf01` y partes del techo. Por ahí se veía afuera del mapa.

**Por qué.** No las borraste vos: el mapa ya salió así de mi primera conversión. El importador de ese momento probaba solo el **centro** de cada cara. Si delante del centro había sólido (el estante pegado a la pared, otro bloque), la daba por "enterrada" y no la dibujaba. Después se corrigió: ahora prueba el centro y cerca de cada esquina, y descarta la cara solo si todo da a sólido o cielo. Pero los mapas ya hechos conservaban el hueco.
* mirage: 83 caras faltantes (mercado, techos `de_mwall44`, `cxdecwdd`, `de_mfence01`, `hwwall`…);
* dust2_cs2: 34 (piso bajo la estructura de madera, cajas `ikcrateb`, `dust_rollupdoor`…).

**Herramienta nueva** (*Textures*, debajo de la luz de CS): **Walls with no texture (see-through): draw again the faces of the .bsp missing**, con el mismo campo del `.bsp`.
* Compara cada cara que hoy dibujaría el importador con los triángulos del mapa (mallas y props): su centro y un punto cerca de cada esquina.
* Si ninguna parte está dibujada, la cara vuelve como malla nueva:
  * con la textura que el mapa ya usa para esa textura de CS;
  * si no hay ninguna, la que tiene el mismo nombre o la que trae el `.bsp`.
* Una cara dibujada en parte cuenta como dibujada, para no superponer dos caras que parpadeen.
* Si el mapa tiene la luz de CS, las caras nuevas la reciben medida contra la de todo el mapa (`lightmap.reference`). Así no salen más claras que el resto. Se agrega una página de luz nueva (`_lm0_2`) y no se toca ninguna textura existente.
* No cambian la colisión, el height map ni las demás mallas. Ojo: también vuelve una cara que hayas borrado a propósito.

**Mapas:** `mp_do_mirage_cs2.zip` y `mp_do_dust2_cs2.zip` rehechos sobre la última versión entregada (con luz y DLL al día):
* mirage: 841 → 883 mallas;
* dust2: 801 → 822 mallas.

**No probado en el juego.**

## 107. DLL comunes para los mapas DO de CS 1.6 y luz de CS en los 8 mapas
### Las dos DLL
Son copias de `mp_DestroyTheTarget.dll`, hechas siempre desde la del juego. La original no se toca.

**`mp_DestroyTheTargetCS.dll`**, una sola para `mp_do_dust2`, `mp_do_dust2_cs2` y `mp_do_mirage_cs2` (los tres zips traen el mismo archivo, byte por byte):
* zonas `bombZone` y `bombZone_B`: hay que volar **las dos** antes de 0:00 para ganar la ronda;
* el mapa trae dos bombas para levantar, una por zona;
* iconos de las zonas en el HUD; el minimapa apunta a la zona más cercana que sigue en pie;
* la bomba explota a los **40 s** de plantada;
* si en 0:00 hay una bomba puesta, el contador muestra los segundos que le quedan y la ronda sigue hasta que explota.

**`mp_DestroyTheTargetCS-Aztec.dll`**, para `mp_do_aztec`: lo mismo, más lluvia sin tormenta (sin truenos ni relámpagos) y salpicaduras en el piso.

Cada escena usa ahora esa DLL. Las copias anteriores (`mp_DestroyTheTarget_mp_do_dust2.dll`, `mp_DestroyTheTargetCS_mp_do_*.dll`, `mp_DestroyTheTarget_mp_do_aztec.dll`) quedan sin usar.

### Luz de CS en todos
`mp_dmt_rifle_india`, `mp_dm_pool_day`, `mp_dmt_pool_day`, `mp_do_dust2`, `mp_dmt_aim_map` y `mp_do_aztec` no la tenían; dust2_cs2 y mirage_cs2 se volvieron a iluminar con los arreglos de abajo.

Arreglos en `lightmap.apply` que aparecieron con los mapas viejos:
* **Triángulos sobre varias caras.** Los mapas hechos con un importador anterior tienen polígonos que cubren varias caras del `.bsp` en un mismo plano. El triángulo tomaba la luz de una sola cara y estiraba su borde sobre las demás: por ejemplo, un triángulo negro en el piso de aim_map, que salía de la sombra de abajo de una caja. Ahora ese triángulo se corta por las caras (`_cut_along_faces`), cada pedazo con su luz. La textura no cambia de lugar.
* **Carteles y tablas finas.** El dorso de un bloque fino está a una unidad del frente y casi siempre oscuro contra la pared. Ahora se elige primero la cara que mira hacia el mismo lado que el triángulo. Esto arregla, por ejemplo, el cartel "FY_POOL RULES", que salía mitad negro.
* **Agua con `!`.** CS la dibuja sin luz; ahora también queda así. El agua de pool_day (`bluewater`, sin `!`) sí lleva luz, como en CS.
* Al iluminar varios mapas seguidos se podía usar la tabla de caras del mapa anterior (caché por dirección de memoria). Corregido.

**No probado en el juego.**

## 108. Bomba en tiempo extra: explota en 0:00 y la ronda siguiente arranca con su tiempo
Problemas del video de prueba (los mismos en todos los mapas DO de CS, porque comparten la DLL):
1. **La bomba explotaba con el reloj en 0:02.** Cuando el reloj llega a 0:00 con una bomba puesta, el código le ponía los segundos que le faltaban a la bomba **más 3**. Ahora le pone **sus propios segundos**: el reloj marca 0:00 cuando explota. Si llega a 0:00 una fracción antes, agrega 0,25 s y sigue marcando 0:00. Si la bomba ya explotó pero la ronda todavía no se dio por ganada, espera de a 0,9 s, también en 0:00, hasta 3 s.
2. **La ronda siguiente arrancaba en 0:03, parada, y ganaba el rojo.** Durante el marcador de fin de ronda el reloj del juego queda congelado (en 0:02). Al reanudarse se le vencía el tiempo de golpe, y ese "0:00" viejo llegaba después de que la ronda nueva ya había puesto 7:00. Antes, la espera de 3 s lo tomaba por propio: ponía 0:03, y después el juego daba la victoria por tiempo al rojo. Con el juego original pasaría lo mismo si una bomba ganaba con menos de un minuto.

Ahora un 0:00 que no es de la ronda actual se ignora y no toca el reloj:
* la ronda ya está ganada (`[escena+0x638]`, "reinicio pendiente");
* o el reloj tiene minutos o más de medio segundo (la ronda nueva ya lo reinició).

Código de la bomba **versión 3**: las copias anteriores aparecen como "desactualizadas" en el editor y se actualizan al volver a aplicar el tiempo de bomba. El harness nativo (`tools/asm/otharness.c`) prueba los casos nuevos.

`mp_DestroyTheTargetCS.dll` y `mp_DestroyTheTargetCS-Aztec.dll` rehechas, y también los 4 zips DO.

**No probado en el juego.**

## 109. DO: una zona volada no admite otra bomba; calcos que parpadeaban; el "espejo" antes de B
### No se puede volver a plantar en una zona ya volada
Cuando hay que volar todas las zonas, la que ya explotó aceptaba otra bomba. La bomba (`mp_bomb.dll`) solo descarta una zona mientras está explotando (`+0x178`, ~60 cuadros). El "Estás en el objetivo / Pon la bomba" sale del radio de la zona: `BombZone::Run` compara la distancia con `[zona+0x160]` y manda `__enterRadius__`.

El código de zonas (`.vtoyz`, `rzero` en `tools/asm/bombzones.s`, cada cuadro):
* cuando una zona queda destruida, guarda su radio y lo pone en 0: nadie "entra" y no se puede plantar;
* cuando el reinicio de la ronda la muestra entera de nuevo, le devuelve el radio;
* si el radio guardado era de otro objeto (otra ronda u otro mapa), lo descarta.

Lo prueba `harness.c`. Las DLL anteriores aparecen como desactualizadas ("a zone already blown up takes a second bomb").

### Calcos que parpadeaban (dust2_cs2, sitio B)
Carteles, molduras y manchas de los mapas de CS son brushes de entidad (`{dust_kasbah`, `{dust_overlay1/2`, `{dust_bsite`, `dust_paper02`…) a **1 unidad** delante de la pared. CS dibuja las entidades después del mundo; Torrente las ordena solo por profundidad, y a la distancia los dos planos se pelean.

Ahora quedan a `bspfix.OVERLAY_GAP` = **4 unidades** de CS de su pared:
* en las importaciones nuevas (`convert(lift=True)`);
* en los mapas ya hechos, con **Blinking decals / dark see-through sheets: fix them from the .bsp** (en *Textures*). Mueve solo los triángulos dibujados con la textura de ese calco, con vértices propios, y conserva su luz.

### El "espejo" antes de entrar a B (dust2_cs2)
Era un rayo de sol: `func_illusionary` aditivo (render mode 5, `fade02` y `black`). CS suma sus colores a la imagen y sus partes negras desaparecen. Torrente lo mostraba como una lámina oscura transparente con bordes negros.

Los brushes aditivos ya no se dibujan (`invisible_entity`). Con la misma herramienta se sacan de los mapas ya hechos, solo los triángulos con la textura de esa cara. Así una pared o un auto pegado a un bloqueador invisible no se tocan.

### Mapas
| Mapa | Triángulos de calcos movidos | Triángulos del rayo sacados |
|---|---|---|
| dust2_cs2 | 195 | 39 |
| mirage_cs2 | 39 | — |
| aztec | 52 | — |
| pool_day (dm / dmt) | 13 | — |

En todos, después de arreglar: 0 caras del `.bsp` faltantes. Las DLL `mp_DestroyTheTargetCS*.dll` fueron rehechas.

**No probado en el juego.**

## 110. mp_do_aztec se cerraba al terminar de cargar: mallas demasiado grandes
**El problema.** La barra de carga llegaba al final y el juego se cerraba sin mensaje. La DLL de aztec (`mp_DestroyTheTargetCS-Aztec.dll`) tiene todos los enganches en orden y los puntos de importación correctos. La diferencia está en el mapa.

**Por qué.** aztec se hizo con un importador anterior, que armaba una malla por textura con todo el mapa adentro. La más grande tenía 7.331 vértices. Con la luz de CS cada vértice ocupa 40 bytes en vez de 32, y quedó en **7.837 vértices: 313 KB** en un solo bloque.

| Mapa | Malla más grande | Tamaño | ¿Funciona? |
|---|---|---|---|
| Mapas del juego | 1.427 vértices | — | sí |
| dust2 (con luz) | — | 234 KB | sí |
| mirage_cs2 | — | 128 KB | sí |
| dust2_cs2 | — | 81 KB | sí |
| aztec (con luz) | 7.837 vértices | 313 KB | no |

Todo lo que funciona está por debajo de 256 KB. No tengo el juego para confirmarlo, pero es lo único de aztec fuera de lo que funciona.

**Herramienta nueva:** **Cut meshes too big for the game (the game closes after loading)**, en *Textures*. Corta cada malla de más de `MESH_MAX_VERTICES` = 2.000 vértices:
* la divide por la mitad del lado más largo, una y otra vez, hasta que cada parte quede por debajo del límite;
* los triángulos, las texturas y la luz quedan iguales;
* la colisión no cambia;
* cada parte queda en los sectores que toca.

Aplicar la luz de CS (`bsp_light`) ahora la usa sola.

**Mapas:**
* aztec: 51 → 55 mallas, la más grande de 1.989 vértices. Mismos 14.541 triángulos, misma área, mismas 2.622 cajas.
* dust2: 34 → 40 mallas.
* pool_day dm / dmt: 26 → 27 mallas.
* rifle_india, aim_map, dust2_cs2 y mirage_cs2 ya estaban por debajo.

**No probado en el juego.**

## 111. dust2_cs2: parpadeos y la caja del medio; mirage_cs2: rejas y barandas que dejan pasar las balas
**Parpadeos (dust2_cs2, también mirage_cs2).** Los videos señalaban dos cosas distintas:
* **Placas finas dibujadas dos veces.** La paja bajo los techos, las rejas, los tablones y las tapas de cajas son placas de 1 a 3 unidades con una cara de cada lado. El juego dibuja cada cara de los dos lados, así que en el mismo lugar quedan dos imágenes casi pegadas que pelean a la distancia. Ahora se dibuja una sola: la otra (la que mira a la pared de al lado) se saca. Herramienta nueva `bspfix.thin_backs`.
* **Calcos tallados en el mundo.** Los paneles tallados de dust2_cs2 (`{dust_kasbah`) no son entidades: son caras del mundo, dos espalda con espalda en el mismo plano, a 1 unidad de la pared. El arreglo de §109 solo miraba entidades, y además un calco apoyado sobre varias caras de pared quedaba sin mover. Ahora también se apartan 4 unidades de la pared. Para reconocer qué triángulo es de cuál cara se mira hacia dónde da cada uno.

El botón **Blinking decals / dark see-through sheets** (en *Textures*) hace las tres cosas en un mapa ya hecho: aparta los calcos, saca los rayos de luz y saca la cara de atrás de las placas finas.

**La caja del medio (dust2_cs2).** Al frente de la caja, detrás del pallet, el importador viejo había dibujado solo un pedazo de la cara: por el resto se veía el cielo. **Walls with no texture (see-through)** ya agregaba las caras que faltaban enteras. Ahora también agrega los pedazos que faltan de una cara dibujada en parte (`bspimport.uncovered_parts`), con su textura y su luz.
* dust2_cs2: 7 pedazos (la caja y 4 más).
* mirage_cs2: 32 pedazos (cajas, libros, maderas).

**Rejas y barandas (mirage_cs2).** La colisión de un mapa de CS sale de su "clip hull": lo sólido agrandado por la caja del jugador. Ahí un hueco más angosto que el jugador queda relleno: entre los barrotes de una ventana, entre los caños de una baranda. La pared queda como una placa entera, y como Torrente usa la misma colisión para jugadores y balas, las balas frenaban en el aire. En CS las balas usan lo sólido de verdad y pasan por los huecos.

Herramienta nueva **Bars, grilles, railings: bullets through the gaps (from the .bsp)**, en *Textures* (`open_bsp_grilles`; también al importar un .bsp nuevo). Para cada pared de la colisión:
* palpa lo sólido de verdad en una grilla de 2 unidades, de frente hasta el fondo de la pared;
* un **hueco** es un lugar vacío con algo sólido de verdad a los dos lados, más cerca que el ancho del jugador (barrote a izquierda y derecha, o caño arriba y abajo);
* un vacío que llega al borde de la pared sin nada del otro lado **no** es hueco: un CLIP invisible (sobre un muro bajo, en el borde del mapa) queda como estaba;
* los barrotes pintados en una textura transparente también cuentan como sólidos donde está el dibujo. La ventana azul de mirage es así: barrotes `{desert_wire51` en un brush que no es sólido, con un CLIP detrás.

La pared se reemplaza por los barrotes, los caños, los postes y el muro alrededor (caras en el .hm y cajas). Las balas pasan por los huecos y los jugadores siguen frenando en la estructura.

Para que un jugador no se meta entre dos postes, solo se abren huecos de hasta 16 unidades de ancho (unos 40 cm). Los huecos entre caños de una baranda (de arriba a abajo) se abren hasta 38 unidades de alto.

mirage_cs2: se recortaron 745 paredes. Las cajas pasaron de 728 a 4.556 y las caras del .hm de 828 a 4.691; el mapa queda en 20.109 cajas en total (antes 16.281). Esto incluye:
* la ventana con rejas del edificio azul: quedan los 6 barrotes y el marco;
* la baranda grande de medio, frente a la pared rosa del agujero: quedan los caños, los postes y el muro de abajo.

También: un panel rompible (`func_breakable` fino) se sacaba siempre como "abierto"; ahora solo si tiene aire de los dos lados, porque un tablón apoyado en una caja tiene que quedar.

**No probado en el juego.**

## 112. mp_do_aztec: el agua del río seguía parpadeando
**Por qué.** aztec se hizo con un importador anterior, que dibujaba todas las caras del agua:
* la superficie;
* la parte de abajo de la superficie, en el mismo plano;
* el fondo, apoyado sobre el lecho del río;
* los costados, apoyados contra las orillas.

Como el juego dibuja cada cara de los dos lados, en el mismo lugar quedaban dos o tres imágenes que se pisaban. El importador de ahora solo dibuja la superficie, pero el mapa ya estaba hecho.

**Arreglo.** El botón **Blinking decals / dark see-through sheets** ahora también saca del mapa los triángulos del agua que el importador ya no dibuja. Solo queda la superficie, que se ve igual desde abajo porque se dibuja de los dos lados.
* Para el agua de una entidad (`func_water`), una cara que mira hacia arriba cuenta como superficie si no tiene agua de la misma entidad encima. Así el agua a distintos niveles conserva cada nivel.
* El agua del mundo (texturas `!`) conserva solo las caras que miran hacia arriba.
* Un triángulo con la textura del agua que cae sobre otra cara del mapa (el lecho, la orilla) ahora sí se saca. Antes se dejaba por si era un tope invisible contra una pared. Ahora solo se deja si esa otra cara tiene la misma textura.
* `thin_backs` ya no mira las caras de agua que no se dibujan. Si no, podía quedarse con la de abajo y borrar la superficie.

**aztec.** Se sacaron 786 triángulos: el agua, que antes tenía 953 triángulos, quedó con los 67 de la superficie. También se sacaron las caras de atrás de 340 triángulos de placas finas (§111). La DLL no cambió.

**No probado en el juego.**

## 113. DO: el juego se cerraba solo unos segundos después de salir del mapa (aztec)
**Qué pasaba.** Al salir de aztec, el juego desarma la escena con su destructor. Este es el orden de la DLL de DO del juego:
1. saca dos sprites;
2. desconecta;
3. borra objetos;
4. `RemoveSceneObjects(6)`: libera los objetos de la escena de una vez;
5. `DeleteSky`;
6. suelta sus sonidos.

Las copias hechas por el editor sacaban la lluvia (`RemoveRenderObject`) y los iconos del HUD (`RemoveSprite`) en el paso 6. Para entonces el paso 4 ya podía haber liberado esos objetos, y se liberaban dos veces. El cierre llega unos segundos después, cuando se reusa esa memoria.

**Confirmado en `vtKernel`:** el constructor de `vtShower` le pone tipo 6 a la lluvia (`[obj+8] = 6`, igual que a los sistemas de partículas de las salpicaduras). `RemoveSceneObjects(6)` borra todos los objetos de tipo 6. Así que la copia vieja borraba la lluvia por segunda vez. Pasa al salir y también cuando la ronda termina y la escena se rehace, como cuando el amarillo gana después de volar los dos sites. Los sprites del HUD son de tipo 2: a esos no los toca.

`mp_deathMatch` saca su propia lluvia de Marbella **al principio** de su destructor, antes de todo eso. Lo vi en su código: `RemoveRenderObject([CGame+0x1334])` antes de `DisconnectClientFromServer` y de `RemoveSceneObjects(6)`. Ahí lo hacía mal la copia de aztec, la única con lluvia. Revisé también lo demás en `vtKernel`: el destructor de la lluvia acepta los truenos vacíos de la lluvia sin tormenta, así que eso no era el problema.

**Arreglo.** El enganche del final de la escena pasa al principio del destructor, en el mismo lugar que usa `mp_deathMatch`: después del primer sprite, en `mov eax,[esi+604h] / test eax,eax`. Son instrucciones sin direcciones absolutas, así que no hay reubicaciones. El código hace lo mismo que antes y después repite esas dos líneas con sus flags (`push` destino / `mov` / `test` / `ret`).
* En el arnés (`harness.c`), el retorno ahora controla `eax` y el flag ZF de esas dos líneas.
* Una copia hecha antes queda marcada como desactualizada ("the game can close by itself a few seconds after leaving the map"). Al rehacerla se restaura el lugar viejo y se engancha el nuevo. Lo probé con la DLL de aztec que te había mandado.

**DLL nuevas:**
* `mp_DestroyTheTargetCS-Aztec.dll` (con lluvia).
* `mp_DestroyTheTargetCS.dll` (sin lluvia). Los iconos del HUD también se sacan ahora en el lugar correcto. Va dentro de los zips de dust2, dust2_cs2 y mirage_cs2.

**No probado en el juego.**

## 114. fy_pool_day: la franja negra al costado del cartel de reglas
**Qué era.** El cartel ("FY_POOL RULES") es un brush de 1 unidad de espesor, a 1 unidad de la pared. Desde §109 su frente se aparta 4 unidades para que no parpadee, pero sus bordes (también de 1 unidad) quedaban pegados a la pared. Con la luz de CS esos bordes salen negros, así que de costado se veía una franja oscura, como una sombra.

**Arreglo.** Los bordes de un calco que se aparta de la pared ya no se dibujan (`bspfix.decal_sides`). Esto vale solo si todo el brush es fino en esa dirección: un calco entero, no una caja que casualmente queda cerca de una pared.
* Al importar un .bsp: se saltean.
* En un mapa ya hecho: los saca el botón **Blinking decals / dark see-through sheets**.

En pool_day son 8 caras: el cartel de reglas y el de "No crapping". Al rehacer pool_day, el mismo botón también sacó la cara de atrás de 404 triángulos de placas finas (§111): azulejos blancos, acero, vidrios. El material se dibuja de los dos lados, así que se siguen viendo.

**Mapas:** `mp_dm_pool_day` y `mp_dmt_pool_day`.

**No probado en el juego.**

## 115. Triángulos encimados al poner la luz de CS (parpadeos), y la espalda de los calcos
**Triángulos encimados.** Al poner la luz de CS, `_cut_along_faces` corta los triángulos que pasan por encima de varias caras del .bsp. Para eso buscaba caras en un margen de 1,5 unidades del plano del triángulo. En el frente de un calco (a 1 unidad de su pared) entraban dos grupos de caras: las del propio calco y las de la pared. Los pedazos de las dos se sumaban, así que el triángulo quedaba cubierto dos veces, cada vez con otra luz, y eso parpadeaba.

Ahora:
* solo se usan las caras del plano más cercano;
* si los pedazos suman más del 102 % del triángulo (caras encimadas), el triángulo queda entero.

Triángulos encimados que había en los mapas ya hechos:

| Mapa | Triángulos encimados |
|---|---|
| dust2_cs2 | 810 (610 de los paneles tallados `dust_kasbah`) |
| aztec | 187 |
| pool_day | 14 (los dos carteles) |
| dust2 | 12 |

Todos se rehicieron. Lo que queda ya venía así en el mapa importado, antes de poner la luz:
* pool_day y dust2: 0;
* dust2_cs2: 15, casi todos dentro de modelos (la limusina);
* aztec: 45, maderas y un generic que en el .bsp ya están repetidos.

**La espalda de los calcos.** El cartel "No crapping" de pool_day tiene la espalda con la textura del otro cartel. Por eso `thin_backs` no la emparejaba con su frente, y la espalda quedaba sobre el plano de la pared, parpadeando con ella. Ahora `decal_sides` también deja afuera la cara de un calco que mira a la pared.

**No probado en el juego.**

## 116. Dos mapas nuevos: mp_do_inferno_csgo y mp_do_cbble_csgo (DO 16 contra 16)
Los dos se hicieron con **New map from CS** (modo DO, 16 por equipo), la luz de CS 1.6 y el DLL compartido de dust2 / mirage (`mp_DestroyTheTargetCS.dll`: las dos zonas, HUD, radar, bomba de 40 s, sin replantar). El DLL no cambió.

| Mapa | De | Texturas | Inicios (CT / T) |
|---|---|---|---|
| `mp_do_inferno_csgo` | `de_inferno_go.bsp` | `inferno_go.wad` (212 de 213; `reflect1`, de `decals.wad`, sale con una textura de Torrente) | 9 / 11 en el .bsp → 16 / 16 |
| `mp_do_cbble_csgo` | `de_cbble_csgo.bsp` | 116 dentro del .bsp, 9 de `halflife.wad` | 16 / 16 |

**Más puntos de inicio.** Si el mapa de CS tiene menos inicios que los pedidos por equipo, ahora el importador agrega los que faltan al lado de los del equipo (`bspimport.more_starts`). Cada uno:
* está sobre el piso, con la caja del jugador libre y lugar alrededor;
* queda a 56 unidades o más de los otros y lejos de los modelos;
* se llega caminando derecho desde el inicio más cercano del equipo (sin pared ni pozo en el medio, escalones de hasta 18).

En inferno se agregaron 7 inicios CT y 5 T.

**Caras apretadas contra otra (parpadeos y manchas oscuras).** En cbble había 602 pares de caras pegadas en el mismo plano, mirando para lados opuestos. Por ejemplo:
* el fondo de una caja (`func_wall`) apoyado en el piso;
* la parte de arriba de una viga contra el techo;
* dos `func_wall` que se tocan.

CS no las muestra. Torrente dibuja cada cara de los dos lados, así que las dos peleaban en el mismo lugar. Herramienta nueva `bspfix.buried_faces`: saca una cara cuando se cumplen las tres condiciones:
* caras opuestas a menos de 0,6 unidades la tapan entera;
* esas caras son de brushes que no dejan ver a través;
* justo delante de ella hay sólido de esos brushes.

Una caja sobre una reja (`{`) queda como está. Ahora el importador no las dibuja, y **Blinking decals / dark see-through sheets** las saca de los mapas ya hechos. Pares que se pisan, antes → después:
* cbble: 602 → 42;
* inferno: 1.789 → 561. Casi todos los que quedan están dentro de modelos (faroles, pallets, tachos) y tienen la misma textura de los dos lados.

**Hojas y carteles de los modelos dibujados dos veces.** Los modelos de CS (yucas, álamos, faroles, pallets de inferno) hacen las hojas con dos triángulos espalda con espalda. En Torrente los dos se dibujan de los dos lados y se pisan. Ahora queda uno de cada par:
* el importador no dibuja el segundo;
* el mismo botón los saca de los mapas ya hechos (`remove_twin_triangles`).

**Arreglo.** Reconstruir caras (`restore_bsp_faces`) se rompía con mapas que tienen calcos. El cálculo de caras faltantes compara cada cara con y sin el calco movido, pero las dos listas no salían iguales: los bordes del calco se dejaban afuera solo en una. Ahora las dos dejan afuera las mismas caras.

Rejas y barandas (§111): en inferno se recortaron 378 paredes y en cbble 295.

**No probado en el juego.**

## 117. Aviso de versión nueva (GitHub)
Al iniciar, el editor busca en segundo plano si hay una versión más nueva en los *releases* de `https://github.com/Lahrenheit/VToyEditorPlus`. No hace esperar: si no hay conexión, no pasa nada.

**Si encuentra una más nueva** que la propia (`APP_REV`, ahora `v1.0.16`), sale un cartel con:
* cuál es (por ejemplo "Hay una versión más reciente del editor: v1.0.17"), cuál es esta, la fecha y las primeras líneas de sus notas;
* el link a su página de GitHub, para descargarla a mano;
* **Descargar y descomprimir junto al programa**:
  * baja el `.zip` del release (o el código fuente si el release no trae `.zip`);
  * lo descomprime en una carpeta **nueva** al lado del programa, por ejemplo `VToyEditorPlus-v1.0.17`;
  * después está el botón **Abrir la carpeta**.

No se pisa nada: el programa que está abierto, `vtoy_editor.json` y los demás archivos quedan como estaban. Para pasar a la versión nueva hay que cerrar el editor y abrir el `VToyEditor` de esa carpeta. Cuando funcione, la carpeta vieja se puede borrar.

**Menús:**
* *Settings > Buscar versiones nuevas al iniciar* prende o apaga la búsqueda (`check_updates` en `vtoy_editor.json`, prendida por defecto). La misma casilla está en el cartel.
* *Help > Buscar versiones nuevas ahora* busca en cualquier momento. Si ya es la última o no hay conexión, también lo avisa.

**Para que funcione**, cada versión tiene que publicarse como *release* en GitHub:
* con un tag con números, por ejemplo `v1.0.17` (se comparan los números con los de `APP_REV`);
* con el `.zip` del programa adjunto (si hay varios, se prefiere uno con "win", "exe" o "editor" en el nombre).

No se cuentan los borradores ni los *pre-release*.

`vtoy/updater.py` (nuevo); los `.bat` de compilación lo incluyen con `--hidden-import vtoy.updater`.

**No probado en Windows:** desde acá no hay acceso a internet ni a la ventana del editor. Probé la búsqueda y la descarga con respuestas simuladas.

## 118. Actualizar solo: .7z, cerrar, reemplazar y volver a abrir
**Releases en .7z.** El archivo del release puede ser `.zip` o `.7z`. Para descomprimir un `.7z` el editor usa, en este orden:
1. `py7zr` (ahora está en `requirements.txt` y `build_exe.bat` lo mete en el .exe);
2. el `7z.exe` de 7-Zip, si está instalado;
3. el `tar.exe` de Windows.

Si ninguno puede, lo avisa: hay que instalar 7-Zip o subir un `.zip`. Si el archivo trae una sola carpeta arriba (por ejemplo `VToyEditor/…`), se usa lo que hay adentro.

**Descargar y actualizar.** El botón del cartel ahora:
1. baja el release y lo descomprime en `_vtoy_update`, al lado del programa;
2. avisa: **"Para actualizar es necesario cerrar el editor: se reemplazan sus archivos por los nuevos y se vuelve a abrir"**;
3. si no hay cambios sin guardar, cuenta 10 segundos y cierra el editor solo.

En el cartel hay dos botones:
* **Cerrar y actualizar ahora**. Si hay cambios sin guardar, primero pregunta si guardarlos, como siempre al salir.
* **Más tarde**: la actualización se hace cuando se cierre el editor.

**Al cerrar** se abre una ventanita de consola que:
1. espera a que el editor termine;
2. copia los archivos nuevos sobre los del programa con `robocopy`, reintentando si alguno sigue bloqueado; `vtoy_editor.json`, `imgui.ini` y `vtoy_editor.log` no se tocan;
3. borra `_vtoy_update`;
4. abre el editor nuevo y se borra a sí misma.

Si la copia falla, la ventana queda abierta y dice dónde están los archivos nuevos para copiarlos a mano.

**Cuándo no reemplaza nada:** si lo descargado no tiene el programa en su primer nivel (`VToyEditor.exe`, o `run_editor.py` + `vtoy` si es el código fuente), o si no es Windows. En esos casos los archivos quedan en `_vtoy_update` con el botón **Abrir la carpeta**.

**Para el release:** subí el contenido de la carpeta `dist\VToyEditor` (`VToyEditor.exe` + `_internal`) comprimido en `.zip` o `.7z`, con un tag como `v1.0.18`.

**No probado en Windows:** desde acá no hay Windows ni internet. Se probó con descargas simuladas: el .zip, el .7z con otra herramienta de descompresión, y el contenido del script de reemplazo.

## 119. Una sola versión: la de cada entrega
Antes había una versión fija, "v1.0", en el título del About y en las propiedades del .exe. Se sacó. Ahora la versión es una sola: `APP_REV` de `vtoy/__init__.py`, que es la que sube en cada entrega (ahora `v1.0.18`).

* **About:** el título dice solo **VToyEditor Plus+**. Debajo, en amarillo, sigue `v1.0.18 - rev fecha hora`.
* **Búsqueda de versiones nuevas (§117):** compara con ese mismo número.
* **Propiedades del .exe** (*Detalles*): versión del archivo y del producto `1.0.18` (`filevers` 1.0.18.0). `version_info.txt` ya no se edita a mano: lo escribe `tools/make_version_info.py` a partir de `APP_REV`. `build_exe.bat` lo corre antes de compilar, así cada .exe sale con su número.

Una prueba verifica que `version_info.txt` coincida con `APP_REV`.

**No probado en Windows** (el .exe no se compiló acá).

## 120. README en tres idiomas, manual de usuario en PDF (español, inglés y portugués)
* **README nuevo** (`README.md`): qué hace el programa, cómo instalarlo y abrirlo, primeros pasos y atajos principales, en **inglés, español y portugués**. El README técnico anterior (§1–§119) pasó a este archivo, `docs/CHANGELOG.md`. Las secciones nuevas se agregan acá.
* **Manual de usuario en tres idiomas**: `docs/Manual_VToyEditorPlus_es.pdf`, `_en.pdf` y `_pt.pdf` (27–28 páginas cada uno). Tienen:
  * carátula con el **icono del programa** (V+), que también está en el encabezado de cada página y en "Acerca de este manual";
  * **índice con enlaces**: cada título lleva a su página, y el pie de cada página tiene **▲ Índice** (▲ Contents) para volver;
  * marcadores del PDF y enlaces entre capítulos.

  Capítulos:
  1. Introducción y las piezas de un mapa
  2. Instalación, configuración y actualizaciones
  3. La pantalla del editor (con un dibujo de sus partes)
  4. Moverse y seleccionar
  5. Editar lo que hay en el mapa
  6. Todas las herramientas del mapa por categoría
  7. Modos de juego y tutorial "un mapa desde cero"
  8. Mapas desde Counter-Strike 1.6
  9. Mapas desde Torrente, el juego
  10. Guardar, probar y compartir
  11. Solución de problemas
  12. Atajos de teclado

  Los nombres de menús y botones son los que muestra el editor en cada idioma.
* **Cómo se arma:** `python tools/make_manual.py` arma los tres; `python tools/make_manual.py en` arma uno solo. Necesita `reportlab` (el editor no). Cada frase está en el script como `t(español, inglés, portugués)`, y la versión sale de `APP_REV`.
* **Ayuda ▸ Manual de usuario (PDF)** abre el manual en el idioma del editor. Si no está, abre el inglés. `build_exe.bat` incluye los tres en el .exe.

## 121. Escaleras de inferno y cbble, objetos con triángulos de luz
Volví a armar **mp_do_inferno_csgo** y **mp_do_cbble_csgo** con estos tres arreglos.

**1. Ranuras en el piso de las escaleras.** La colisión del piso sale del "hull" de CS, y en las escaleras quedaba cortada en pedazos con ranuras de 4 a 13 cm sin piso, de lado a lado de la escalera:
* en una escalera de inferno, la pendiente sobre los escalones tenía una ranura de 5 unidades en el medio;
* en cbble, cada pisada terminaba unos cm antes de la rampa del escalón siguiente.

En el juego, ahí el jugador no encuentra piso: se frena o se traba en cada escalón. Función nueva `bspimport.bridge_plane_gaps`: cierra la ranura con una tira que une los dos bordes cuando se cumplen estas condiciones:
* dos pisos tienen bordes enfrentados (hasta 18° de diferencia);
* están a menos de 40 cm uno del otro;
* sus alturas difieren menos de 20 cm;
* no hay ya otro piso en ese lugar.

Un jugador de CS (81 cm de ancho) nunca cae por esas ranuras, así que nunca son a propósito.

Si del otro lado de la ranura el piso está más abajo (hasta 46 cm), se pone una rampa de escalón que baja desde el borde de arriba hasta ese piso. Es el caso de las escaleras de cbble: la pisada terminaba 9 cm antes del escalón y el contraescalón estaba cortado. Si la caída es más alta, es un borde de verdad y queda como está.

Puntos con ranura (barrido de todo el mapa):

| Mapa | Antes | Después |
|---|---|---|
| cbble | 304 | 91 |
| inferno | 309 | 356 |

Lo que queda en inferno está casi todo en una línea de techos (a 458 unidades de altura, donde no se juega), que el barrido ahora cuenta porque del otro lado hay un piso nuevo. Las escaleras que revisé de los dos mapas quedaron sin ninguna ranura.

**2. Rampas de los escalones.** Cada escalón de hasta 46 cm se convierte en una rampa dos veces más larga que alta. Cuando la pisada es más corta que eso, el pie de la rampa quedaba colgando sobre la rampa de abajo y formaba un escalón. Ahora la rampa termina donde termina su pisada (`_tread`), así que la escalera queda como una sola pendiente pareja.

**Botón nuevo** en *Aspecto ▸ Texturas* (sección de CS): **Escaleras: volver a hacer la colisión del piso desde el .bsp** (`rebuild_bsp_floor`). Rehace todo el `.hm` del mapa con estas reglas, en un solo paso de deshacer. Las cajas de colisión quedan como están. Si el mapa tiene rejas o barandas, después hay que apretar otra vez el botón de rejas.

**3. Objetos con triángulos claros y oscuros.** Con la luz de CS, cada triángulo de un objeto (modelos, cajas, piezas de pared que no coinciden con ninguna cara del .bsp) tomaba la luz del piso que tenía debajo de su propio centro. Por eso un objeto salía en parches de triángulos claros y oscuros. Ahora:
* **una pieza de pared o piso** que las caras del .bsp no tapan del todo toma la luz de la cara de al lado, en su propio lugar (`lightmap._beside_faces`);
* **un objeto** (triángulos unidos por sus esquinas) toma una sola luz: la del piso debajo de su centro, como CS ilumina sus modelos (`lightmap.objects_of`).

**No probado en el juego.**

## 122. inferno y cbble: pared invisible en banana, escaleras donde uno se hundía, el canal, tachos y cuadros
Volví a armar **mp_do_inferno_csgo** y **mp_do_cbble_csgo** con estos arreglos. Todos están en la importación de mapas de CS y en el botón **Escaleras: volver a hacer la colisión del piso desde el .bsp** (que ahora también cambia las cajas de colisión que corresponden).

**1. Pared invisible en banana (inferno).** El hull agachado de CS (hull 3, el que usa la colisión desde §91) tenía, por un error del compilador, un hueco vacío debajo del piso de banana. La pared de ese hueco salía 56 cm por encima del piso, de lado a lado de la calle, y además llevaba cajas de colisión detrás: frenaba a los jugadores y a las balas. Una pared real nunca atraviesa un piso por el medio, así que ahora:
* una pared con el mismo piso de los dos lados de su borde de arriba se recorta hasta ese piso (`bspimport.trim_pierced_walls`);
* sus cajas de colisión se rehacen con la pared recortada.

En inferno se recortaron 465 paredes; en cbble, 381.

**2. Escaleras donde uno se hundía (cbble).** Debajo de la rampa de cada escalón quedaba la pisada plana original, unos cm más abajo. Además, debajo de las escaleras que en CS son una entidad sólida (`func_wall`) quedaba el piso de la calle. En el juego el jugador terminaba en esos pisos de abajo: se hundía en la escalera, quedaba caminando adentro y a veces caía bajo el mapa. Ahora (`bspimport.drop_buried_floors`):
* se saca la parte de un piso que tiene otro piso a menos de 85 cm encima (ahí nadie entra: en CS el agachado mide 91 cm);
* debajo de la parte de arriba de una entidad sólida (escalera, caja) se saca el piso del mapa a cualquier profundidad, hasta la base de la entidad. Un puente en el aire no cuenta: el piso queda.

**3. Escalones chicos sin contraescalón.** Cuando el escalón es chico, o pertenece a otro sólido (el primer escalón de una escalera `func_wall`, de 20 cm, o el escalón de 10 cm del canal de inferno), el hull no deja pared debajo del borde. Entonces `step_ramps` no hacía rampa y el jugador se frenaba ahí. Ahora el borde de un piso que está sobre otro piso más bajo (hasta 46 cm), sin pared debajo, lleva una rampa hasta abajo (`bspimport.lip_ramps`): 980 en inferno y 944 en cbble.

**4. Pasos para agacharse.** CS tiene pasos que solo se atraviesan agachado, como el desagüe al final del canal de inferno, cuyo dintel está a 1,3 m del piso. El jugador de Torrente no se agacha: el dintel lo frenaba, y como al canal se entra saltando desde 1,2 m, quedaba encerrado. Las paredes que cuelgan entre la altura de agachado (80 cm) y la de parado (183 cm), con piso de los dos lados, se sacan (`bspimport.drop_hanging_walls`). El jugador pasa parado.

**5. Cerrar trampas.** Botón nuevo en *Buscador de caídas y trampas*: **Cerrar las trampas** (`close_traps`). Recorre el mapa como un jugador desde los puntos de aparición y busca lugares a los que se cae pero de los que no se sale caminando (por ejemplo, el pozo de cbble que en CS se sale por una escalera de mano). En cada borde por donde se cae ahí pone cajas de colisión invisibles. La prueba de caminar (`navgrid`) ahora también ve las caídas por encima de un borde con pared debajo: antes la pared de abajo cortaba el paso y esos lugares no aparecían ni en el *Buscador de caídas y trampas*. Los mapas llevan:
* inferno: 2 trampas cerradas con 62 cajas: el canal (por el borde de la calle y por la entrada del costado) y un hueco debajo de una escalera;
* cbble: 9 trampas cerradas con 186 cajas, entre ellas el pozo de la escalera de mano y las franjas de 40 cm entre la escalera `func_wall` y las paredes (quedan 13 chicas, de 1–2 lugares, sin tocar).

En los dos mapas, desde los puntos de inicio T se sigue llegando caminando a los dos sitios de bomba y a la base CT.

**6. Objetos con caras casi negras (los tachos azules).** CS ilumina un brush chico, como un barril, con uno o dos puntos de luz por cara. Esos puntos muchas veces caen adentro de la pared o del barril de al lado, así que una cara salía casi negra al lado de otra clara. Ahora una cara chica (hasta 48 unidades) toma al menos 0,55 de la luz habitual de las caras que la rodean (`lightmap.lift_small_faces`). La sombra se mantiene y desaparecen los parches negros. En un rincón oscuro, donde todo alrededor está oscuro, la cara sigue oscura.

**7. Cuadros que parpadeaban (cbble).** El estandarte CT está 2 unidades delante de la pared, encima de una chapa de revoque que está a 1 unidad. Las dos se movían a 4 unidades de la pared y quedaban en el mismo plano, así que parpadeaban. Ahora un decal puesto encima de otro queda 2 unidades delante de ese otro (`overlay_shifts(layered=True)`). *Corregir decals* también arregla los mapas hechos antes: encuentra los decals que una versión vieja ya había movido y los lleva al lugar nuevo.

Comprobado con la prueba de caminar del editor, no en el juego:
* banana: no hay pared ni caja por encima del piso en la línea del hueco, y desde T se sube por banana hasta B;
* el canal de inferno: el escalón de 10 cm tiene rampa y no se puede caer adentro;
* la escalera `func_wall` de cbble: no queda ningún piso debajo de las rampas ni debajo de la escalera;
* tachos de A en inferno: la cara más oscura pasó de 36 a 60 (de 255), las claras siguen en 135–140;
* el estandarte CT de cbble quedó a 5 cm de la chapa de atrás (antes, en el mismo plano).

**No probado en el juego.**
