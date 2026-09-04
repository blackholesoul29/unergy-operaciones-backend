# Anatomía de un módulo Origina — guía de migración

Referencia canónica: dominio `payment/` + capa HTTP `api/v2/origination/payment/`.
Convenciones generales: `api/CLAUDE.md` (REST), `CLAUDE_DOMAIN.md` (dominio).

---

## 0. La regla estructural: dos árboles, nunca uno

El dominio y la API son **dos árboles de directorios separados**. El dominio no sabe
que existe HTTP; la API no calcula nada. Si venís de un solo árbol
(`controllers/ services/ models/`), el corte va exactamente donde termina el request.

### Árbol A — dominio (una app Django por contexto de negocio)

```
payment/
├── apps.py                # ready() → import payment.signals
├── models.py              # ORM + métodos de instancia
├── admin.py
├── signals.py             # efectos colaterales; best-effort, nunca trabajo pesado
├── utils/dates.py         # funciones puras sin ORM
├── services/              # ◀ EL NÚCLEO. Un paquete por área, no un services.py gigante
│   ├── concept/
│   │   ├── base.py              # ABC ConceptServiceBase + lógica compartida
│   │   ├── registry.py          # @register(tipo) + get_service(tipo, **kwargs)
│   │   ├── project.py advance.py personalized.py termsheet.py
│   │   ├── calculators.py       # cálculo puro, sin estado ni ORM
│   │   └── tests/test_*.py      # los tests viven junto al service
│   ├── payment/payment_service.py
│   ├── files/ notification/ odoo/ zapsign/ reconciliation/ landlord/
├── tasks/                 # un archivo = una task Celery
│   ├── payment/generate_payment.py mark_as_paid.py ...
│   └── concept/generate_concepts.py
├── management/commands/
└── migrations/            # incluye seeds de periodic tasks (0002_seed_...)
```

`payment/views.py` está vacío a propósito (solo el comentario del scaffold):
**una app de dominio no tiene vistas.**

### Árbol B — API (versionada, anidada por dominio y por recurso)

```
api/v2/origination/payment/
├── urls.py            # SOLO include() de cada sub-recurso. Ni un router acá.
├── pagination.py      # paginación del módulo (hereda de api/pagination.py)
│
├── payment/           # ◀ un directorio por RECURSO expuesto
│   ├── urls.py            # router.register("payment", views.TerrainPaymentViewSet, ...)
│   ├── views.py           # el ViewSet: orquesta, valida params, delega
│   ├── serializers.py     # la forma del JSON, entrada y salida
│   ├── queryset.py        # las consultas y el armado de la respuesta
│   └── tests.py
├── concept/           # + queryset.py, registry de serializers por tipo
├── terrain/           # + services.py (escrituras multi-fila del endpoint)
├── project/           # + services.py
├── termsheet/         # solo views + serializers (recurso simple)
└── landlord/          # + schema.py (metadata del stepper, pydantic)
```

Cada recurso es un **directorio**, no un archivo. Simple = 3 archivos
(`urls/views/serializers`); complejo agrega `queryset.py`, `services.py`,
`filter.py`, `schema.py`. Nunca un archivo que no haga falta.

### Quién puede qué

| Capa | Archivo | Su único trabajo | Nunca |
|---|---|---|---|
| Ruta | `urls.py` | Registrar el ViewSet en un router y anidarlo | Lógica, condicionales, imports de modelos |
| Vista | `views.py` | Permisos, validar query params, elegir serializer/queryset, paginar, delegar | Calcular montos, `.filter()` complejos, APIs externas |
| Queryset | `queryset.py` | Consultas ORM reusables, anotaciones, prefetch, agregados | Escribir en BD, decidir permisos, formatear |
| Serializer | `serializers.py` | Forma y validación del JSON; traducir tipos | Reglas de negocio en `create()`; consultas por fila |
| Service de API | `<recurso>/services.py` | Orquestar una escritura del endpoint | Reglas que otro consumidor también necesite |
| Service de dominio | `<app>/services/<área>/` | Toda la regla de negocio | Tocar `request`, `Response`, excepciones DRF |
| Modelo | `models.py` | Persistencia + lógica de la propia instancia | Lógica que necesite otras tablas o servicios |

**El pipeline y su dirección:** `urls.py → views.py → queryset.py / serializers.py / services/`.
La vista importa de los otros tres; ninguno importa de la vista. Un import en sentido
contrario es la primera señal de que una capa se metió en el trabajo de otra.

---

## 1. Rutas: `include()` hasta el recurso

```python
# originabot/urls.py
path("api/", include("api.urls"))
# api/urls.py
path("v2/", include("api.v2.urls"))
# api/v2/urls.py
path("origination/", include("api.v2.origination.urls"))
# api/v2/origination/urls.py
path("payment/", include("api.v2.origination.payment.urls"))

# api/v2/origination/payment/urls.py — SOLO includes, un sub-recurso por línea
urlpatterns = [
    path("terrain/",   include("api.v2.origination.payment.terrain.urls")),
    path("concept/",   include("api.v2.origination.payment.concept.urls")),
    path("payment/",   include("api.v2.origination.payment.payment.urls")),
]

# api/v2/origination/payment/payment/urls.py — acá y solo acá, el router
router = routers.DefaultRouter()
router.register("payment", views.TerrainPaymentViewSet, basename="payment-payments")
urlpatterns = [path("", include(router.urls))]
```

- Siempre `DefaultRouter`, nunca `path()` a mano para un ViewSet (las `@action` se registran solas).
- `basename` explícito y único en todo el proyecto: es la clave del `reverse()`.
- Un router puede registrar varios ViewSets del mismo recurso (`terrain/urls.py`).
- `urlpatterns = router.urls` cuando registrás con prefijo vacío (`concept/urls.py`).

---

## 2. ViewSets: mixins explícitos y nada de cálculo

```python
@class_logger_wrapper(name="Origination | Payment | Terrain Payments")
class TerrainPaymentViewSet(
    viewsets.GenericViewSet, mixins.ListModelMixin, mixins.UpdateModelMixin
):
    """Historial de pagos — un item por Payment que incluye algún concepto
    del terreno pedido, más reciente primero.

    GET ?terrain=<id>[&year=YYYY&month=MM]     ← el contrato se documenta ACÁ
    """

    permission_classes = [IsAuthenticated, PaymentRolePermissions]
    required_role = ["payment_manager", "payment_visualizer"]
    pagination_class = BasePagination
    http_method_names = ["get", "patch", "head", "options"]   # sin PUT
    queryset = pt_models.Payment.objects.all().prefetch_related("concept_links")

    def get_serializer_class(self):
        if self.action == "partial_update":
            return PaymentCommentSerializer      # escritura
        if self.action == "preview":
            return PreviewPaymentSerializer      # action custom
        return TerrainPaymentSerializer          # lectura

    def list(self, request, *args, **kwargs):
        terrain_id = request.query_params.get("terrain", "")
        # Sin esto un valor no numérico llega al ORM y revienta en 500.
        if not terrain_id.isdigit():
            raise ValidationError({"terrain": "Debe ser el id entero del recurso."})

        payment_query = payment_queryset.get_terrain_payments(   # ← consulta
            terrain_id,
            year=request.query_params.get("year"),
            month=request.query_params.get("month"),
        )
        page = self.paginate_queryset(payment_query)
        items = payment_queryset.build_payment_breakdown(        # ← agregado
            page if page is not None else payment_query
        )
        serializer = self.get_serializer(items, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def notify(self, request, pk=None):
        """Notifica al usuario para que suba la documentación de pagos."""
        payment = self.get_object()
        success, response = PaymentNotificationService(payment).notify()  # ← negocio
        if success:
            return Response({"message": "Se notificó al usuario..."})
        raise ValidationError(f"No se pudo notificar al usuario {response}")
```

Reglas:

- **Mixins explícitos, no `ModelViewSet` por defecto.** Solo las acciones que el recurso
  expone de verdad. `ModelViewSet` únicamente si el CRUD completo es real (`landlord/views.py`).
- **`http_method_names` para cerrar verbos** que un mixin trae de regalo
  (`UpdateModelMixin` da PUT y PATCH; acá PUT no aplica).
- **`get_queryset()` ramifica por `self.action`**: el detalle necesita anotaciones que el
  listado no paga, y el write path no necesita ninguna (`terrain/views.py`).
- **`get_serializer_class()` ramifica por `self.action`.** Lectura y escritura nunca comparten serializer.
- **El docstring de la clase es la documentación del contrato**: query params, obligatorios,
  campos escribibles, qué se audita.
- **`@class_logger_wrapper(name=...)` en toda clase** y `@log_endpoint(name=...)` en cada
  `@action` custom (el wrapper solo cubre CRUD estándar). Patrón: `"Dominio | Módulo | Recurso"`.
- **Errores solo con excepciones DRF**: `ValidationError`, `NotFound`, `PermissionDenied`.
  Nunca excepción Python pelada, nunca `Response(status=400)` a mano.

### Validación de query params: en la vista, siempre

```python
terrain_id = request.query_params.get("terrain", "")
if not terrain_id.isdigit():
    raise ValidationError({"terrain": "Debe ser el id entero del recurso."})

# params mutuamente excluyentes (termsheet/views.py::has_payment)
if bool(terrain_id) == bool(project_id):
    raise ValidationError("Especifica exactamente uno de 'terrain' o 'project'.")

# recurso que no tiene sentido sin filtro: queryset vacío, no error
def get_queryset(self):
    terrain = self.request.query_params.get("terrain")
    if terrain is None:
        return ts_models.LandLord.objects.none()   # early return, sin query
    return ts_models.LandLord.objects.payment_view(terrain=terrain)
```

### Permisos: rol declarado en la vista

JWT validado por gRPC en middleware; los roles llegan como lista de strings en
`request.user.roles`. La vista solo declara qué roles necesita.

```python
permission_classes = [IsAuthenticated, PaymentRolePermissions]
required_role = ["payment_manager", "payment_visualizer"]

# PaymentRolePermissions descarta los roles de solo-lectura antes de evaluar
# métodos no seguros: listar "payment_visualizer" NUNCA habilita POST/PATCH/DELETE.
# "is_administrator" pasa siempre.

# Permisos distintos por acción (terrain/views.py)
WRITE_ACTIONS = ("update", "partial_update")

def get_permissions(self):
    if self.action in self.WRITE_ACTIONS:
        self.required_role = ["payment_manager", "payment_visualizer"]
        return [IsAuthenticated(), PaymentRolePermissions()]
    return super().get_permissions()
```

> El chequeo va en `has_permission`, no en `has_object_permission`: DRF no llama el
> object-level en `list` ni en `create`, así que un permiso solo object-level deja el
> POST abierto.

---

## 3. Querysets: el archivo que casi nadie migra bien

Un `queryset.py` por recurso, con **funciones a nivel de módulo** (no clases) que reciben
ids y devuelven querysets o estructuras listas para serializar. Toma tres formas:

```python
# ── 1. Un Q reusable: el criterio de negocio escrito UNA vez ──────────
def terrain_concepts_q(terrain_id, prefix="") -> Q:
    """`prefix` es la ruta ORM completa hasta el Concept, para aplicar el MISMO
    filtro desde distintos modelos: "" desde Concept, "concept__" desde
    PaymentConcept, "concept_links__concept__" desde Payment."""
    termsheet_ids = mf_models.Project.objects.filter(
        terrain_id=terrain_id, termsheet__isnull=False
    ).values("termsheet_id")
    return Q(**{f"{prefix}project__terrain_id": terrain_id}) | Q(
        **{f"{prefix}termsheet_id__in": termsheet_ids}
    )


# ── 2. La consulta del endpoint: filtros + select/prefetch + orden ────
def get_terrain_payments(terrain_id, year=None, month=None) -> QuerySet[Payment]:
    scoped_concepts = Prefetch(
        "concept_links",
        queryset=PaymentConcept.objects.filter(
            terrain_concepts_q(terrain_id, "concept__")
        ).select_related("concept", "concept__project", "concept__termsheet")
         .prefetch_related("concept__deductions"),
        to_attr="scoped_concept_links",     # ◀ el serializer lee este atributo
    )
    payments = Payment.objects.filter(
        terrain_concepts_q(terrain_id, "concept_links__concept__"),
        land_lord_id__in=landlord_ids,
    )
    if year:  payments = payments.filter(date__year=year)
    if month: payments = payments.filter(date__month=month)
    return (payments.distinct()
            .select_related("land_lord")
            .prefetch_related(scoped_concepts)
            .order_by("-date"))


# ── 3. Función pura de armado: anota el desglose sobre las instancias ──
def build_payment_breakdown(payments) -> list[Payment]:
    """No son datos aparte del pago, así que se anotan como atributos de la
    misma instancia en vez de envolverla en un dict con clave "payment"."""
    for payment in payments:
        pcs = payment.scoped_concept_links
        payment.rent = [pc for pc in pcs if pc.concept.type == ConceptType.PROJECT]
        payment.advances = [pc for pc in pcs if pc.concept.type == ConceptType.ADVANCE]
        payment.summary = {"total_rent": ..., "total_to_pay": ...}
    return list(payments)
```

Reglas:

- **Funciones, no clases.** Reciben ids y kwargs planos. Sin `self.request`: así las reusa
  un test, una task y el previsualizador por igual.
- **Un criterio de negocio se escribe una vez** como `Q` parametrizado por `prefix`.
  Reimplementarlo en tres lugares es cómo se desincronizan los endpoints.
- **`Prefetch(..., to_attr=...)` para acotar relaciones**, no filtrar en Python después.
- **El módulo lleva docstring largo explicando el modelo de datos**: los caminos hacia el
  terreno, por qué hay `distinct()`, qué está ya calculado y qué no.
- **Los agregados se calculan sobre TODO el queryset, no sobre la página** — un total que
  cambia al paginar es un bug (`concept/queryset.py::build_pending_summary`).
- **Prohibido escribir**: ni `.save()`, ni `.update()`, ni `create()`.

### Managers vs `queryset.py`

Dos lugares, el corte es por audiencia:

- **Manager/QuerySet del modelo** (`<app>/manager.py`, `<app>/queryset.py`): filtros de
  negocio que usa todo el proyecto — `Terrain.objects.payment_view()`.
- **`api/.../<recurso>/queryset.py`**: la consulta específica de ese endpoint.

La vista compone las dos:
`terrain_queryset.with_payment_fields(queryset.payment_view_detail())`.

---

## 4. Serializers: uno por dirección, uno por granularidad

**Lectura y escritura nunca son el mismo serializer**, y el detalle nunca es el mismo que
el listado.

| Rol | Ejemplo real | Base | Qué expone |
|---|---|---|---|
| Referencia anidada | `ProjectRefSerializer` | `ModelSerializer` | 2–4 campos: `id`, `name` |
| Entrada de lista | `RentEntrySerializer` | `ModelSerializer` | Una fila del desglose |
| Agregado sin tabla | `PaymentSummarySerializer` | `Serializer` plano | Totales del queryset |
| Lectura principal | `TerrainPaymentSerializer` | `ModelSerializer` | El recurso con sus anidados |
| Variante | `PreviewPaymentSerializer` | subclase de la anterior | Mismo contrato, campo anulado |
| Escritura | `PaymentCommentSerializer` | `ModelSerializer` | Solo campos escribibles |

```python
class TerrainPaymentSerializer(serializers.ModelSerializer):
    """`rent`/`advances`/`summary` se anotan como atributos sobre la instancia
    en build_payment_breakdown; acá se leen por su nombre, igual que cualquier
    campo real del modelo."""

    status = ChoiceDisplayField(choices=pt_models.PaymentStatus.choices)
    land_lord = _LandLordRefSerializer()
    rent = RentEntrySerializer(many=True)          # ← atributo anotado, no relación
    advances = AdvanceEntrySerializer(many=True)
    summary = PaymentSummarySerializer()
    support_document = serializers.SerializerMethodField()

    class Meta:
        model = pt_models.Payment
        fields = ["id", "date", "status", "comment", "land_lord",
                  "support_document", "rent", "advances", "summary"]

    def get_support_document(self, obj) -> dict | None:
        """Se prefiere el documento que el propietario DEVOLVIÓ (file_received)
        sobre el que Unergy le envió (file_sent): el primero es el respaldo real."""
        if obj.file_received:
            return {"file": _cached_file_url(obj.file_received), "signed": True}
        if obj.file_sent:
            return {"file": _cached_file_url(obj.file_sent), "signed": False}
        return None


class PaymentCommentSerializer(serializers.ModelSerializer):
    """Serializer aparte del de lectura A PROPÓSITO: el de lectura expone el
    desglose acotado al alcance, que no existe fuera del contexto de la lista."""

    class Meta:
        model = pt_models.Payment
        fields = ["id", "comment"]
        read_only_fields = ["id"]
```

### Campos reutilizables: `api/fields.py`

Antes de escribir un `SerializerMethodField`, buscar si el campo ya existe:

```
CentsField           # centavos → pesos con 2 decimales. TODO el dinero.
ChoiceDisplayField   # choice → {"value": "paid", "display": "Pagado"}
FileValueField       # ruta en B2 → URL de descarga (None si no hay archivo)
FileWithStatusField  # {url, status} leyendo dos anotaciones de la instancia
YesNoBooleanField    # bool ↔ "si"/"no", y aparece como select en OPTIONS
SafeIntegerField     # entero tolerante a "" y None (gRPC, CSV)
```

**Regla de dinero, sin excepciones:** en la BD todo monto es entero en **centavos**
(`BigIntegerField`); en el JSON sale en **pesos**. La conversión la hace `CentsField` al
salir y el serializer de escritura al entrar (`validated_data["amount"] * 100`). Nunca
floats en el modelo, nunca centavos en la respuesta. La única excepción está comentada en
el código con su motivo.

### Escritura: `create()` delega, no decide

```python
_SERIALIZER_REGISTRY: dict[str, type] = {}

def register_serializer(concept_type: str):
    def decorator(cls):
        _SERIALIZER_REGISTRY[concept_type] = cls
        return cls
    return decorator

def get_concept_serializer(concept_type: str) -> type | None:
    return _SERIALIZER_REGISTRY.get(concept_type)


class BaseConceptSerializer(serializers.ModelSerializer,
                            metaclass=_ConceptSerializerMeta):
    class Meta:
        model = pt_models.Concept
        fields = ("id", "type", "amount", "date")

    @abstractmethod
    def build(self, validated_data): ...      # cada subclase arma su Concept

    def create(self, validated_data):
        # Los ConceptService levantan ValueError plano para reglas de negocio.
        # Sin este try/except DRF no lo reconoce como APIException → 500.
        try:
            concept = self.build(validated_data)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))
        concept.save()
        return concept


@register_serializer(pt_models.ConceptType.PERSONALIZED)
class PersonalizedConcept(BaseConceptSerializer):
    project = serializers.PrimaryKeyRelatedField(queryset=..., write_only=True)
    amount = serializers.IntegerField(min_value=1)
    comment = serializers.CharField(max_length=512)

    class Meta(BaseConceptSerializer.Meta):
        fields = BaseConceptSerializer.Meta.fields + ("project", "amount", "comment")
        read_only_fields = ("date",)          # la fecha la decide el service

    def validate(self, data):
        BeneficiaryValidator().check_project_beneficiaries(data["project"])
        return data

    def build(self, validated_data):
        return get_service(                   # ← el negocio vive en payment/services/
            pt_models.ConceptType.PERSONALIZED,
            project=validated_data["project"],
            amount=validated_data["amount"] * 100,   # pesos → centavos
            comment=validated_data["comment"],
        ).create()
```

Y la vista solo elige, sin conocer los tipos:

```python
def get_serializer_class(self):
    if self.action == "create":
        type_ = self.request.data.get("type")
        serializer_cls = concept_serializers.get_concept_serializer(type_)
        if serializer_cls is None:
            raise ValidationError({"type": f"Unsupported concept type: '{type_}'"})
        return serializer_cls
    return concept_serializers.ConceptInfoSerializer
```

Reglas:

- `validate_<campo>()` para una regla de un campo; `validate()` cuando cruza campos.
- `write_only=True` en los pk de entrada, objeto anidado en la respuesta: el cliente manda
  `project: 12` y recibe `project: {id, name}`.
- `read_only_fields` para lo que decide el sistema (`date`, `amount` calculado,
  `created_at`). Un campo declarado arriba no puede repetirse ahí — DRF lo rechaza.
- `@transaction.atomic` en el `create()` cuando la operación crea más de una fila.
- `SerializerMethodField` solo para lectura calculada, **nunca con una consulta adentro**:
  si hace falta un dato externo por fila, se precarga en el contexto con un mixin
  (`api/mixins.py::SupplyContextMixin`).
- **Subclasificar antes de duplicar.** `PreviewPaymentSerializer` hereda todo el contrato y
  solo anula `id` y `sign_url`: así el historial y el preview no se desincronizan.

---

## 5. Services: dos niveles, y el importante no está en la API

"Service" significa dos cosas distintas según dónde viva el archivo, y la diferencia no es
de tamaño: es de **audiencia**.

| | Service de dominio | Service de API |
|---|---|---|
| Dónde | `payment/services/<área>/*.py` | `api/v2/.../<recurso>/services.py` |
| Quién lo llama | Vistas, tasks, comandos, admin, signals, otros services | Un solo endpoint |
| Forma | Clase con estado (`__init__` + métodos) o funciones puras | Funciones a nivel de módulo |
| Sabe de HTTP | No — levanta `ValueError` | Sí — levanta `ValidationError` de DRF |
| Tests | `services/<área>/tests/test_*.py` | `<recurso>/tests.py` |
| Ejemplo | `PaymentService`, `PersonalizedConceptService`, `LandlordTax` | `update_landlord_terrain_percentages` |

### A. Service de dominio — donde vive el negocio

Una clase por operación: el constructor recibe los objetos con los que trabaja, los métodos
son pasos nombrados, y hay un método terminal que persiste. Patrón clave:
**separar "armar" de "guardar"**, para que un previsualizador muestre exactamente lo que la
corrida real va a crear.

```python
class PaymentService:
    """Genera un único pago por propietario, sumando los conceptos asociados
    y aplicando el porcentaje según su participación en proyecto o terreno."""

    def __init__(self, landlord: ts_models.LandLord, date: datetime):
        self.landlord = landlord
        self.date = date

    def concepts_repository(self) -> QuerySet[Concept]:
        # Dedup POR PROPIETARIO (no por concepto): un Concept es compartido por
        # todos los copropietarios, cada uno con su payment_percentage.
        return (Concept.objects.filter(date__date=self.date.date())
                .exclude(payment_links__payment__land_lord=self.landlord)
                .filter(PAYABLE_STAGE_Q)
                .annotate(paid_total=concept_paid_total_subquery())
                .filter(paid_total__lt=F("amount") * (1 - TOLERANCE))
                .select_related("project", "termsheet", "project_configuration")
                .prefetch_related("deductions").distinct())

    def get_percentage(self, concept) -> float: ...
    def calculate_concepts(self) -> tuple[int, list[PaymentConcept]]: ...

    def build_payment(self) -> tuple[Payment, list[PaymentConcept]]:
        """El Payment tal como quedaría, SIN guardar nada. El cálculo vive acá y
        no dentro de process_payment para que el previsualizador muestre
        EXACTAMENTE lo que la corrida va a crear: si recalculara los impuestos
        por su cuenta, divergiría en la primera regla fiscal que cambie."""
        total, payment_concepts = self.calculate_concepts()
        tax = LandlordTax(self.landlord.responsability_type)   # ← otro service
        payment = Payment(amount=total, iva=tax.calc_iva(total), ...)
        for pc in payment_concepts:
            pc.payment = payment
        return payment, payment_concepts

    def process_payment(self) -> Payment:
        payment, payment_concepts = self.build_payment()
        with transaction.atomic():
            payment.save()      # .save() y no create(): el save() asigna alt_id
            PaymentConcept.objects.bulk_create(payment_concepts)
        # Fuera de la transacción: si falla el documento, el pago ya existe y
        # puede reintentarse sin riesgo de duplicado.
        generate_payment_documents(payment)
        return payment
```

Además de la clase, el mismo módulo expone **funciones a nivel de módulo** para decisiones
que otros consumidores necesitan sin instanciar nada (`concept_dates_in_window()`,
`landlords_for_date()`, `as_payment_datetime()`) y **constantes con el criterio de negocio**,
para que exista una sola vez:

```python
# Se usa en las dos direcciones (filter en el service, exclude en la task para
# loggear lo omitido) para que el criterio exista una sola vez.
PAYABLE_STAGE_Q = Q(project__isnull=True) | Q(project__stage__in=Project.PAYMENT_STAGES)

# Los porcentajes de copropietarios tienen 3 decimales, así que la suma pagada
# puede quedar por debajo del monto exacto aunque TODOS cobraron.
CONCEPT_SETTLED_ROUNDING_TOLERANCE = Decimal("0.001")
```

### El registry: una familia de services intercambiables

Cuando una operación tiene variantes por tipo, no se usa `if/elif`. Cada variante es un
archivo que se auto-registra, y agregar un tipo nuevo **no toca ningún archivo existente**:

```python
# base.py — el contrato y lo compartido
class ConceptServiceBase(ABC):
    @abstractmethod
    def get_payment_date(self) -> datetime.date: ...
    @abstractmethod
    def create(self) -> pt_models.Concept: ...

    def first_payment_date(self, project) -> datetime.datetime:
        """Lógica compartida por varias implementaciones."""
        ...

# registry.py — "Agregar un tipo nuevo = crear el archivo y decorar la clase."
_REGISTRY: dict[str, type[ConceptServiceBase]] = {}

def register(concept_type: str):
    def decorator(cls):
        _REGISTRY[concept_type] = cls
        return cls
    return decorator

def get_service(concept_type: str, **kwargs) -> ConceptServiceBase:
    cls = _REGISTRY.get(concept_type)
    if not cls:
        raise ValueError(f"Unsupported concept type: '{concept_type}'")
    return cls(**kwargs)

# Auto-import al final del módulo: los @register corren al importar cada archivo.
from payment.services.concept import advance, personalized, project, termsheet  # noqa

# personalized.py — una implementación
@register(pt_models.ConceptType.PERSONALIZED)
class PersonalizedConceptService(ConceptServiceBase):
    def __init__(self, project, amount: int, comment: str):
        self.project = project
        self.amount = amount          # en centavos
        self.comment = comment

    def get_payment_date(self):
        return self.first_payment_date(self.project)

    def create(self) -> pt_models.Concept:
        return pt_models.Concept(...)   # devuelve SIN guardar: guarda el serializer
```

### B. Service de API — orquestar una escritura del endpoint

```python
# api/v2/origination/payment/terrain/services.py
def update_landlord_terrain_percentages(terrain_id: int, items: list) -> list:
    ids = [item["id"] for item in items]
    records = {r.id: r for r in LandLordTerrain.objects.filter(
        id__in=ids, terrain=terrain_id)}

    for item in items:
        record = records.get(item["id"])
        if not record:      # pertenencia: el id existe pero no es de este terreno
            raise ValidationError(
                {"id": f"LandLordTerrain {item['id']} no pertenece a este terreno."})
        record.payment_percentage = item["payment_percentage"]

    for record in records.values():
        record.save(update_fields=["payment_percentage"])   # update_fields explícito
    return list(records.values())


# …y la @action de la vista: valida, delega, serializa. Tres líneas de trabajo.
@action(detail=False, methods=["post"])
@log_endpoint(name="Origination | Payment | LandLord Terrain | percentages")
def percentages(self, request):
    serializer = LandLordTerrainPercentageUpdateSerializer(
        data=request.data, many=True)
    serializer.is_valid(raise_exception=True)
    records = terrain_services.update_landlord_terrain_percentages(
        request.query_params.get("terrain"), serializer.validated_data
    )
    return Response(LandLordTerrainSerializer(records, many=True).data)
```

> **La pregunta que decide dónde va el código:** ¿lo necesitaría una task de Celery, un
> management command o el admin? Si sí —o podría serlo— va en `<app>/services/`. Si solo
> tiene sentido como parte de ese request, va en `api/.../<recurso>/services.py`.
> En duda, al dominio: mover de dominio a API nunca hizo falta; al revés, sí.

---

## 6. Tasks, signals y modelos

### Tasks: un archivo por task, la lógica en el service

```python
# payment/tasks/payment/generate_payment.py
logger = get_logger("Payment Generation")

@app.task
def generate_payments(date_str=None, days_ahead=0, payment_day=None) -> dict:
    """Genera un pago por cada propietario con conceptos en la fecha dada."""
    for target_date in concept_dates_in_window(...):        # ← del service
        for landlord in landlords_for_date(target_date):    # ← del service
            PaymentService(landlord=landlord, date=...).process_payment()

# encolar, siempre con cola explícita
generate_payments.apply_async(args=[obj.id], queue="synchronizer")
```

| Situación | Cola | Workers |
|---|---|---|
| PDFs, emails, documentos | `default` | 2 |
| Odoo u otra API externa pesada | `synchronizer` | 2 |
| Tracking de estado, timeline, auditoría | `tracker` | 1 — el orden importa |
| Web Push | `webpush` | 1+ |

La periodicidad no se hardcodea: `DatabaseScheduler` desde el admin, y el registro inicial
va como **migración de seed** (`0002_seed_payment_periodic_tasks.py`). Así se cambia una
frecuencia sin deploy.

### Signals: efectos colaterales, y best-effort

```python
# payment/apps.py — el único lugar donde se registran
class PaymentConfig(AppConfig):
    name = "payment"
    def ready(self):
        import payment.signals  # noqa: F401

# payment/signals.py
@receiver(pre_delete, sender=pt_models.Payment)
def delete_document_from_zapsign(sender, instance, **kwargs):
    """La limpieza remota es best-effort: corre dentro de pre_delete, así que si
    fallara hacia arriba impediría borrar el pago. Se loggea y se sigue — dejar
    un documento huérfano en ZapSign es preferible a no poder borrar."""
    if not instance.zapsign_token:
        return
    try:
        ZapSign.delete_document(instance.zapsign_token)
    except requests.RequestException as exc:
        logger.error("Error eliminando documento en ZapSign", data={...})
```

- **Nada de trabajo pesado en un signal**: consultas grandes o HTTP se delegan a una task.
- **Todo lo externo va en `try/except`** con log, para no bloquear la operación local.
- **Ninguna regla de negocio en un signal.** Solo derivados y notificaciones.

### Modelos

- **Base abstracta común** para timestamps (`class Timer(models.Model)` con
  `created_at`/`updated_at` y `Meta.abstract = True`).
- **`TextChoices` para todo estado**: `PaymentStatus`, `ConceptType`. Nunca strings sueltos.
- **`verbose_name` en cada campo y en `Meta`** — es lo que se ve en el admin, y acá está en español.
- **Métodos de instancia solo si dependen de la propia instancia**: `get_sign_url()`,
  `upload_to()`. Si necesita otras tablas, es un service.
- **`on_delete` deliberado**: `PROTECT` para lo contable, `CASCADE` solo para hijos que no
  valen nada solos.

---

## 7. Un recurso nuevo, de cero (el orden importa: de adentro hacia afuera)

1. **Modelo** en `<app>/models.py`, con `TextChoices`, `verbose_name` y `Meta`. Después
   `makemigrations <app>` — una migración por PR.
2. **Reglas de negocio** en `<app>/services/<área>/<nombre>_service.py`. Si hay variantes
   por tipo: `base.py` (ABC) + `registry.py` + un archivo por variante.
3. **Test del service** en `<app>/services/<área>/tests/test_<nombre>.py`. `SimpleTestCase`
   + `MagicMock(spec=Modelo)`: con `spec`, acceder a un atributo que el modelo real no tiene
   lanza `AttributeError`, así el test detecta un método movido de lugar.
4. **Directorio del recurso**: `api/v2/<dominio>/<módulo>/<recurso>/` con `__init__.py`.
5. **`serializers.py`**: los `*RefSerializer` anidados, el de lectura, el de escritura.
   Dinero con `CentsField`, choices con `ChoiceDisplayField`.
6. **`queryset.py`** si la consulta pasa de unas pocas líneas o se comparte: funciones que
   reciben ids, con `select_related`/`prefetch_related` donde el serializer los va a leer.
7. **`views.py`**: ViewSet con los mixins justos, `permission_classes` + `required_role`,
   `pagination_class`, `get_queryset()`/`get_serializer_class()` ramificando por acción,
   `@class_logger_wrapper`, y docstring con el contrato.
8. **`services.py` del recurso** solo si hay una escritura multi-fila que orquestar.
9. **`urls.py`**: `DefaultRouter`, `register(..., basename=...)` único; y el `include()` en
   el `urls.py` del módulo padre.
10. **`tests.py`** del recurso, sobre las funciones de `queryset.py` y los serializers. Se
    usan dobles (`SimpleNamespace`) en vez de fixtures reales: `Project`/`Terrain` exigen PostGIS.
11. **Revisión final**: ¿la vista tiene algún cálculo? ¿el serializer tiene una consulta?
    ¿el queryset escribe? ¿el service de dominio importa algo de DRF? Cualquier "sí" es
    código en la capa equivocada.

---

## 8. Lo prohibido

- **Cálculo de negocio en la vista o el serializer.** Fórmula, porcentaje o regla fiscal
  fuera de `<app>/services/` está mal ubicada.
- **Un `ModelViewSet` "por si acaso".** Expone create/destroy que nadie pidió ni testeó.
- **Lectura y escritura con el mismo serializer.** Termina en campos calculados que el
  cliente puede escribir, o en `read_only` esparcidos por todas partes.
- **Una consulta dentro de un `SerializerMethodField`.** Es un N+1 por fila.
- **Query params sin validar.** Un `?terrain=abc` llega al ORM y sale como 500 en Sentry.
- **Excepciones Python peladas desde una vista.** Un `ValueError` de un service es un 500
  hasta que alguien lo traduce a `ValidationError`.
- **Llamar una API externa desde una vista o un signal.** Va en un service, invocado desde
  una task con cola explícita.
- **Reimplementar un criterio de negocio.** Si está escrito en dos lugares, en algún momento
  van a diferir. Se extrae como `Q` o constante.
- **`print()` en cualquier parte.** Los logs van a ELK vía `logger.logger.get_logger`.
- **Floats para dinero.** Centavos entero en la BD, pesos en el JSON, conversión solo en el borde.
- **Migraciones con `RunPython` sin lotes** sobre tablas grandes: bloquea.

---

## 9. Traducción desde otro framework

| Lo que traés | Acá es | Ojo con |
|---|---|---|
| Router / route file | `<recurso>/urls.py` + `DefaultRouter` | No se declara ruta por ruta; el router las deriva del ViewSet |
| Controller | `views.py` → `ViewSet` | Un ViewSet ≠ un controlador: no calcula, decide y delega |
| Middleware de auth | Ya existe: `GRPCAuthenticationMiddleware` | Los roles llegan en `request.user.roles` |
| Guard / policy | `api/permissions.py` + `required_role` en la vista | El chequeo va en `has_permission`, no solo object-level |
| DTO / schema de entrada | Serializer de escritura | Uno por acción, no uno por modelo |
| DTO / presenter de salida | Serializer de lectura + `api/fields.py` | El campo reusable ya existe: buscar antes de escribir |
| Service / use case | `<app>/services/<área>/` | Un paquete por área, no un `services.py` de 2000 líneas |
| Repository | `manager.py` / `queryset.py` del modelo | No se escribe capa de repositorio: el Manager ya lo es |
| Job / worker | `<app>/tasks/<área>/<task>.py` + `@app.task` | Cola explícita en `apply_async`; nunca lógica en la task |
| Cron | `django_celery_beat` + migración de seed | La frecuencia se cambia desde el admin, sin deploy |
| — | **`api/.../<recurso>/queryset.py`** | No tiene equivalente. Es donde deja de crecer el controlador |
| — | **Docstrings de contrato** | El contrato del endpoint se documenta en el ViewSet; el modelo de datos, en el docstring del `queryset.py` |
