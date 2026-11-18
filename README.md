# SynthID

Detección de identidades sintéticas y anillos de solicitud de crédito sobre
una base de datos de **grafos** (Neo4j AuraDB, managed service en la nube).

El fraude de identidad sintética no roba una identidad completa: **recombina
fragmentos reales con datos falsos**. Una CURP válida con un nombre inventado,
un teléfono nuevo y un domicilio real. Expediente por expediente, cada
solicitud pasa las validaciones; el fraude solo aparece al mirar la **red de
atributos compartidos** entre solicitudes que, en teoría, no tienen nada que
ver. Eso es exactamente lo que un grafo hace bien y una tabla no.

## Estado del proyecto

| Fase | Contenido | Estado |
|---|---|---|
| 0 | Conexión a AuraDB y configuración | Listo |
| 1 | Esquema: constraints e índices | Listo |
| 2 | Datos semilla con anillos sembrados | Listo |
| 3 | CRUD completo (read / update / delete) | Listo |
| 4 | Módulo de detección y scoring | Listo |
| 5 | API FastAPI y demo guiada | Listo |
| 6 | Documento de justificación NoSQL | Pendiente |

## Puesta en marcha

### 1. Crear la instancia en la nube

1. Entra a [console.neo4j.io](https://console.neo4j.io) y crea una instancia
   **AuraDB Free** (no requiere tarjeta; 200 000 nodos y 400 000 relaciones).
2. Al crearla, Aura muestra las credenciales **una sola vez**. Descarga el
   archivo o cópialas de inmediato.

### 2. Configurar el entorno

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# El archivo que descarga Aura ya tiene el formato correcto: solo renombralo.
cp ~/Downloads/<archivo-de-aura> .env
```

**No edites ese archivo.** En AuraDB el usuario y la base de datos se llaman
como el **ID de la instancia** (p. ej. `ab0cd36a`), no `neo4j`. Verificado con
`SHOW DATABASES` contra la instancia real: la única base de usuario es la del
ID y no existe ninguna llamada `neo4j`. Si "corriges" esos campos a `neo4j`,
la conexión falla con `Neo.ClientError.Security.Unauthorized` (el usuario) o
`DatabaseNotFound` (la base).

Dos trampas más, por si la conexión falla:

- Un archivo descargado de una instancia que luego **borraste** ya no sirve,
  aunque la instancia nueva tenga el mismo nombre. Compara el host del URI
  con el ID que muestra la consola.
- Aura pide **esperar unos minutos** tras crear la instancia antes de
  conectarse (lo dice en la primera línea del propio archivo).

### 3. Verificar, crear esquema y poblar

```bash
python scripts/check_conexion.py   # confirma que la nube responde
python scripts/init_db.py          # constraints e índices
python scripts/seed.py             # 427 solicitudes: 400 legítimas + 5 anillos
```

El seed tarda unos segundos y es **idempotente**: correrlo dos veces no
duplica nada.

### Scripts disponibles

| Script | Qué hace |
|---|---|
| `scripts/check_conexion.py` | Verifica conectividad y versión del motor |
| `scripts/init_db.py` | Aplica el esquema. `--mostrar` solo lo lista |
| `scripts/seed.py` | Puebla la base. `--solo-anillos`, `--poblacion N` |
| `scripts/reset_db.py` | Borra los datos (pide confirmación). `--todo` borra también el esquema |

## Modelo de datos

**Nodos**

```
(:Solicitud   {id, fecha, monto_solicitado, estatus, score_riesgo})
(:Persona     {id, nombre_completo, fecha_nacimiento})
(:Curp        {valor})
(:Telefono    {numero})
(:Email       {direccion})
(:Domicilio   {clave, calle, cp, ciudad})
(:Dispositivo {fingerprint, tipo})
(:CuentaBanco {clabe})
(:Empleador   {nombre})
```

**Relaciones**

```
(:Solicitud)-[:PRESENTADA_POR]->(:Persona)
(:Persona)-[:TIENE_CURP]->(:Curp)
(:Solicitud)-[:USA_TELEFONO]->(:Telefono)
(:Solicitud)-[:USA_EMAIL]->(:Email)
(:Solicitud)-[:RESIDE_EN]->(:Domicilio)
(:Solicitud)-[:ORIGINADA_EN]->(:Dispositivo)
(:Solicitud)-[:DEPOSITO_A]->(:CuentaBanco)
(:Persona)-[:TRABAJA_EN]->(:Empleador)
```

### Las tres decisiones de diseño que sostienen el proyecto

**1. El PII es nodo, no propiedad.** Un teléfono no es una columna de la
solicitud: es una entidad con identidad propia a la que varias solicitudes
pueden apuntar. En el momento en que se modela así, el anillo de fraude deja
de ser un patrón que hay que buscar y se vuelve una **estructura topológica
navegable**.

**2. Las constraints de unicidad son el motor del modelo.** Son lo que hace
que `MERGE (t:Telefono {numero: ...})` reutilice el nodo existente en vez de
duplicarlo. La red de atributos compartidos se teje sola en el alta, sin
código de reconciliación. Si faltan las constraints, cada solicitud queda en
su propia isla y **ninguna consulta de detección encuentra nada**: por eso
`init_db.py` corre antes del seed.

**3. `Empleador` queda fuera del traversal de detección.** Cientos de
personas legítimas comparten empleador. Medido sobre los datos semilla: un
traversal de 8 saltos desde una solicitud legítima alcanza **0** solicitudes
si se recorre solo el PII identificador, y **98** si se incluye `TRABAJA_EN`.
De ahí la lección generalizable: en un grafo de fraude hay que distinguir los
atributos compartidos que son **identificadores** (teléfono, dispositivo,
CURP, CLABE) de los que son meras **categorías** (empleador, ciudad, banco).

Nota técnica: `Domicilio` llevaría naturalmente una llave compuesta
(calle + CP + ciudad), pero las *node key* compuestas son exclusivas de Neo4j
Enterprise. Se deriva una propiedad `clave` normalizada (mayúsculas, espacios
colapsados) y la unicidad se aplica sobre ella. La normalización no es
cosmética: sin ella `Av.  Reforma 12` y `av. reforma 12` serían domicilios
distintos y partirían un anillo en dos componentes.

## Los datos semilla

`scripts/seed.py` genera dos capas. Los datos son **100 % sintéticos**: CURP,
CLABE y teléfonos tienen formato plausible pero se generan al azar.

**Capa A — 400 solicitudes legítimas** con PII totalmente único. Es el ruido
de fondo contra el que se mide la señal. Comparten empleador entre sí, porque
eso es normal.

**Capa B — cinco anillos sembrados**, cada uno diseñado para que lo cace una
consulta distinta:

| Anillo | Patrón sembrado | Lo detecta |
|---|---|---|
| **A** Granja de CURP | 1 CURP, 6 personas con nombres distintos | Una CURP, varios nombres |
| **B** Dispositivo compartido | 8 solicitudes, 8 personas, 1 fingerprint | Nodos hub con grado anómalo |
| **C** Cadena larga | S1—tel—S2—domicilio—S3—dispositivo—S4—CLABE—S5 | Traversal `*1..8` y `shortestPath` |
| **D** Mula de depósito | 5 solicitudes sin relación aparente, 1 CLABE | Vecindad a 2 saltos |
| **E** Falso positivo | Una familia real: 3 solicitudes, mismo domicilio y teléfono fijo | **Ninguna** debería marcarlo |

El anillo **E** es deliberado y es la mejor carta en la defensa del proyecto:
permite hablar de umbrales, precisión y del costo de un falso positivo en
lugar de solo presumir que la consulta encuentra cosas. Compartir domicilio es
normal; lo que distingue a esa familia del anillo D es que cada integrante
tiene CURP, dispositivo y cuenta propios, y que comparten apellido.

El anillo **C** tiene **8 saltos** entre sus extremos, así que las consultas
de anillo usan cota `*1..8`, no `*1..6`.

Tras correr el seed, `docs/anillos_sembrados.json` guarda los valores
compartidos de cada anillo (la CURP del A, el fingerprint del B, los extremos
del C...) para copiarlos a Neo4j Browser durante la demo. El generador es
determinista: la misma semilla produce exactamente los mismos datos, así que
ese archivo sigue siendo válido tras volver a poblar.

## Verificación hecha

El código de las fases 0–2 corre **contra la instancia real de AuraDB**
(Neo4j 5.27-aura, enterprise): esquema aplicado y 427 solicitudes insertadas
en 10 s. Las 6 consultas de detección encuentran los 5 anillos y cero falsos
positivos entre las 400 legítimas, con resultados idénticos a la validación
local — lo que confirma que el generador es determinista entre entornos.

Antes de eso se validó contra un Neo4j 5.26 en contenedor, para no consumir
cuota de Aura mientras se afinaba el Cypher:

- 40 comprobaciones offline del generador: unicidad del PII legítimo,
  estructura de los 5 anillos, ausencia de contaminación entre capas,
  determinismo entre corridas y formatos de CURP/CLABE/teléfono.
- Esquema aplicado: 9 constraints + 4 índices propios.
- Seed completo en 1.7 s. Conteos resultantes consistentes con el diseño:
  427 `Solicitud` y `Persona`, 422 `Curp` (−5 por el anillo A), 419
  `Dispositivo` (−8 por B y C), 422 `CuentaBanco` (−5 por D y C), 424
  `Telefono` y 424 `Domicilio` (−3 por C y E), 3 416 relaciones.
- Idempotencia: segunda corrida del seed → conteos idénticos.
- Las consultas de detección encuentran los 5 anillos y **cero** falsos
  positivos entre las 400 legítimas. `shortestPath` entre los extremos del
  anillo C devuelve los 8 saltos con la cadena de evidencia completa.

## Las seis consultas especializadas

En `src/detection.py`. Todas recorren solo `REL_PII`, la lista blanca de
relaciones a atributos **identificadores**, y todas llevan cota de
profundidad explícita.

| Función | Paradigma | Qué responde |
|---|---|---|
| `atributos_compartidos(id)` | Vecindad a 2 saltos | ¿Con quién comparte PII esta solicitud? |
| `anillo_de(id, profundidad)` | Traversal de longitud variable | ¿Quiénes forman su clúster completo? |
| `ruta_entre(a, b)` | `shortestPath` | ¿Cómo se conectan dos solicitudes "ajenas"? |
| `curps_multiples()` | Agregación sobre vecinos | ¿Qué CURP tiene varios nombres? |
| `hubs(tipo, mínimo)` | Grado anómalo | ¿Qué atributo usan demasiadas personas? |
| `anillos_globales()` | Barrido de la base | Tablero del analista, sin partir de una solicitud |

`atributos_compartidos` usa `*1..2` porque la CURP pende de la `Persona`, no
de la `Solicitud`. Las cotas se interpolan en el Cypher (y se validan como
enteros antes) porque Cypher **no acepta parámetros en los rangos de
longitud**: `*1..$n` es inválido.

## El score de riesgo

En `src/scoring.py`. Las señales no se suman: se combinan como probabilidades
independientes (noisy-OR), `riesgo = 1 - Π(1 - pᵢ)`. Sumar desborda rápido y
obliga a recortar en 100, con lo que dos señales fuertes y cinco se vuelven
indistinguibles; con noisy-OR cada señal nueva aporta cada vez menos, que es
como funciona la evidencia acumulada. El peso de cada atributo refleja cuánto
cuesta compartirlo por casualidad: CURP 0.50, CLABE 0.45, dispositivo 0.40,
teléfono y email 0.30, domicilio 0.10.

Resultados medidos sobre los datos semilla:

| Solicitud | Score | Nivel | Señal principal |
|---|---|---|---|
| `SOL-A-01` | 98.8 | ALTO | CURP compartida con 5 solicitudes |
| `SOL-B-01` | 96.9 | ALTO | Dispositivo compartido con 7 |
| `SOL-D-01` | 96.3 | ALTO | CLABE compartida con 4 |
| `SOL-C-01` | 72.0 | ALTO | Teléfono compartido con 1, en un clúster de 5 |
| `SOL-E-01` | 18.1 | **BAJO** | Mitigado como familia |
| `SOL-L-0001` | 0.0 | BAJO | Sin atributos compartidos |

El caso interesante es `SOL-C-01`: por sí sola, compartir un teléfono con una
sola solicitud es una señal débil. Lo que la eleva a ALTO es el **tamaño del
clúster** que revela el traversal — pertenece a una cadena de 5. Esa señal no
existe sin el grafo.

### La mitigación familiar

Un domicilio y un teléfono fijo compartidos por tres personas del mismo
apellido es una familia, no un anillo. Sin esta regla el anillo E sale en
**72.4 puntos (ALTO)**, que sería un falso positivo caro: se le niega el
crédito a tres clientes legítimos. La regla es deliberadamente estrecha —
solo aplica si **ningún** identificador fuerte está compartido — porque una
familia también puede cometer fraude.

## La API

```bash
uvicorn src.api:app --reload
```

El Swagger autogenerado queda en <http://127.0.0.1:8000/docs> y es la mejor
superficie para la demo: se hace clic en cada endpoint y se ve el CRUD y los
traversals en vivo, sin teclear comandos.

| Método | Ruta | Qué hace |
|---|---|---|
| `POST` | `/solicitudes` | Alta, y devuelve el score calculado en el acto |
| `GET` | `/solicitudes` | Listado paginado, filtrable por estatus |
| `GET` | `/solicitudes/{id}` | Expediente completo |
| `PATCH` | `/solicitudes/{id}/estatus` | Decisión del analista |
| `PATCH` | `/solicitudes/{id}/telefono` | Reapunta la relación a otro nodo |
| `DELETE` | `/solicitudes/{id}` | Baja + purga de huérfanos |
| `GET` | `/solicitudes/{id}/riesgo` | Score con los motivos que lo explican |
| `GET` | `/solicitudes/{id}/anillo` | Clúster completo vía traversal |
| `GET` | `/investigacion/ruta?a=&b=` | Cadena de evidencia (`shortestPath`) |
| `GET` | `/alertas/curps-multiples` | CURPs con varios nombres |
| `GET` | `/alertas/hubs?tipo=` | Atributos con grado anómalo |
| `GET` | `/alertas/anillos` | Barrido global |
| `GET` | `/salud` | Verifica que la API alcanza la nube |

Dos decisiones que vale la pena señalar:

**Los endpoints son `def`, no `async def`.** El driver de Neo4j es síncrono y
bloqueante. Declarado `async def`, una consulta lenta bloquearía el event loop
y con él *todas* las peticiones concurrentes; declarado `def`, FastAPI lo
ejecuta en su threadpool y el bloqueo queda aislado a un hilo.

**Los endpoints de riesgo verifican existencia antes de evaluar.** Sin esa
comprobación, un id inexistente devolvería `score 0 / nivel BAJO`: una
respuesta plausible y equivocada. Ahora devuelve 404.

Códigos verificados contra la instancia real: 200, 404 (inexistente y ruta sin
camino), 409 (id duplicado) y 422 (formato inválido y tipo de hub no
soportado).

## La demo guiada

```bash
python scripts/demo.py            # recorrido completo
python scripts/demo.py --pausar   # espera Enter entre pasos
python scripts/demo.py --limpiar  # quita restos de una corrida interrumpida
```

Seis pasos: alta limpia (score 0) → alta que cae en el anillo B (96.9) →
traversal del clúster → cadena de evidencia de 8 saltos del anillo C →
barrido de alertas → el falso positivo del anillo E y la discusión del umbral.

Las solicitudes que crea usan el prefijo `SOL-DEMO-` y se borran al terminar,
así que la base queda en 427.

## Tests

```bash
python -m pytest tests/ -v
```

25 tests de integración contra la instancia real (no hay mocks: lo que hay
que verificar es que el Cypher se comporta como se cree contra el motor).
Requieren el seed cargado. Cada test de CRUD limpia lo que crea, borrando por
prefijo `SOL-TEST-` con un `MATCH` directo.

## Operación

- **AuraDB Free pausa la instancia tras 3 días de inactividad.** Reanúdala en
  [console.neo4j.io](https://console.neo4j.io) y corre `check_conexion.py`
  **el día anterior** a la evaluación.
- El `.env` nunca se sube al repositorio (está en `.gitignore`). Si pierdes
  el password de Aura hay que recrear la instancia y volver a poblar.
- Toda consulta de longitud variable lleva cota superior explícita
  (`*1..8`, `*..10`): un traversal sin cota sobre un grafo con hubs explota.

## Estructura

```
.
├── src/
│   ├── config.py       # carga y validación del .env
│   ├── db.py           # driver Neo4j, sesiones, helpers de lectura/escritura
│   ├── schema.py       # constraints e índices
│   ├── repository.py   # CRUD completo (el MERGE que teje la red)
│   ├── detection.py    # las seis consultas de grafo
│   ├── scoring.py      # score de riesgo y mitigación familiar
│   ├── models.py       # esquemas Pydantic de la API
│   └── api.py          # endpoints FastAPI
├── tests/
│   ├── conftest.py
│   ├── test_crud.py
│   └── test_detection.py
├── scripts/
│   ├── check_conexion.py
│   ├── init_db.py
│   ├── seed.py         # generador de las dos capas de datos
│   ├── demo.py         # recorrido narrado para la evaluación
│   └── reset_db.py
├── docs/
│   └── anillos_sembrados.json   # generado por el seed
├── requirements.txt
└── .env.example
```
