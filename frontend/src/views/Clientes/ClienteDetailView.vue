<template>
  <div class="space-y-4" v-if="cliente">
    <!-- Header -->
    <div class="flex items-center gap-3">
      <button @click="$router.push('/clientes')"
        class="text-sm flex items-center gap-1 hover:underline" style="color: #915BD8;">
        <i class="pi pi-arrow-left text-xs" /> Clientes
      </button>
      <span style="color: #c5b9db;">/</span>
      <span class="text-sm font-semibold" style="color: #2C2039;">{{ cliente.razon_social_nombre }}</span>
    </div>

    <!-- Tabs -->
    <div class="bg-white rounded-xl shadow-sm overflow-hidden" style="border: 1px solid #e8e0f0;">
      <div class="flex border-b" style="border-color: #e8e0f0;">
        <button v-for="tab in tabs" :key="tab.key"
          @click="activeTab = tab.key"
          class="px-5 py-3 text-sm font-medium transition-colors border-b-2 -mb-px"
          :style="activeTab === tab.key
            ? 'border-color: #915BD8; color: #915BD8;'
            : 'border-color: transparent; color: #6b5a8a;'">
          <i :class="tab.icon + ' mr-1.5 text-xs'" />{{ tab.label }}
        </button>
      </div>

      <div class="p-6">

        <!-- ── Tab: Información ── -->
        <div v-if="activeTab === 'info'">
          <ClienteForm :initial="cliente" @save="saveInfo" @cancel="() => {}" :inline="true" />
        </div>

        <!-- ── Tab: Servicios ── -->
        <div v-if="activeTab === 'servicios'" class="space-y-4">
          <div class="flex items-center justify-between">
            <p class="text-sm" style="color: #6b5a8a;">Servicios que Unergy presta a este cliente.</p>
            <button @click="abrirDialogoServicio"
              class="px-4 py-2 rounded-lg text-sm font-semibold text-white flex items-center gap-1.5"
              style="background: #915BD8;">
              <i class="pi pi-plus text-xs" /> Agregar servicio
            </button>
          </div>

          <div v-if="cliente.servicios.length === 0" class="text-center py-10 text-sm" style="color: #9b89b5;">
            Ningún servicio registrado aún.
          </div>

          <div v-else class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div v-for="s in cliente.servicios" :key="s.id"
              class="rounded-xl p-4 space-y-2"
              style="border: 1.5px solid #e8e0f0;">
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-3">
                  <div class="w-9 h-9 rounded-lg flex items-center justify-center text-white text-xs font-bold"
                    :style="{ background: servicioColor(s.tipo) }">
                    {{ s.tipo[0].toUpperCase() }}
                  </div>
                  <div>
                    <p class="text-sm font-semibold capitalize" style="color: #2C2039;">{{ servicioLabel(s.tipo) }}</p>
                    <p v-if="s.fecha_inicio" class="text-xs" style="color: #9b89b5;">
                      Desde {{ formatDate(s.fecha_inicio) }}
                    </p>
                  </div>
                </div>
                <button @click="confirmarEliminarServicio(s)" class="text-red-400 hover:text-red-600 transition-colors">
                  <i class="pi pi-trash text-sm" />
                </button>
              </div>

              <!-- Documentos vinculados al servicio -->
              <div class="pt-1 space-y-1">
                <template v-for="tipo in ['oferta', 'contrato']" :key="tipo">
                  <div class="flex items-center justify-between rounded-lg px-3 py-1.5"
                    style="background: #f8f5fd;">
                    <div class="flex items-center gap-2">
                      <span class="text-xs font-semibold px-1.5 py-0.5 rounded-full"
                        :style="tipo === 'oferta' ? 'background:#f0ebfd;color:#915BD8' : 'background:#e8f5e9;color:#2e7d32'">
                        {{ tipo === 'oferta' ? 'Oferta' : 'Contrato' }}
                      </span>
                      <span v-if="docDeServicio(s.id, tipo)" class="text-xs truncate max-w-32" style="color:#2C2039;">
                        {{ docDeServicio(s.id, tipo).archivo_nombre || docDeServicio(s.id, tipo).nombre }}
                      </span>
                      <span v-else class="text-xs italic" style="color:#bba8d4;">Sin archivo</span>
                    </div>
                    <div class="flex items-center gap-1">
                      <a v-if="docDeServicio(s.id, tipo)?.archivo_url"
                        :href="docDeServicio(s.id, tipo).archivo_url" target="_blank"
                        class="text-xs hover:underline flex items-center gap-0.5" style="color: #915BD8;">
                        <i class="pi pi-external-link text-xs" />
                      </a>
                      <button v-if="docDeServicio(s.id, tipo)"
                        @click="abrirDialogoDocumento(docDeServicio(s.id, tipo))"
                        class="text-xs hover:text-purple-700" style="color:#6b5a8a;">
                        <i class="pi pi-pencil" />
                      </button>
                      <button v-else @click="abrirDialogoDocumento(null, tipo, s.id)"
                        class="text-xs font-medium" style="color:#915BD8;">
                        + Subir
                      </button>
                    </div>
                  </div>
                </template>
              </div>
            </div>
          </div>
        </div>

        <!-- ── Tab: Documentos ── -->
        <div v-if="activeTab === 'documentos'" class="space-y-5">
          <div class="flex items-center justify-between">
            <p class="text-sm" style="color: #6b5a8a;">Documentos del cliente: identificación y comerciales.</p>
            <button @click="abrirDialogoDocumento(null)"
              class="px-4 py-2 rounded-lg text-sm font-semibold text-white flex items-center gap-1.5"
              style="background: #915BD8;">
              <i class="pi pi-plus text-xs" /> Agregar documento
            </button>
          </div>

          <!-- Identificación -->
          <div>
            <h3 class="text-xs font-bold uppercase tracking-wide mb-2" style="color: #9b89b5;">
              Identificación del cliente
            </h3>
            <div v-if="docsIdentificacion.length === 0"
              class="text-sm text-center py-6 rounded-xl" style="color:#bba8d4; border: 1.5px dashed #e8e0f0;">
              Sin documentos de identificación. Agrega el RUT, certificado bancario o cámara de comercio.
            </div>
            <div v-else class="space-y-2">
              <div v-for="doc in docsIdentificacion" :key="doc.id"
                class="flex items-center justify-between rounded-xl px-4 py-3"
                style="border: 1.5px solid #e8e0f0;">
                <div class="flex items-center gap-3">
                  <span class="text-xs font-bold px-2 py-0.5 rounded-full whitespace-nowrap"
                    :style="badgeStyle(doc.tipo)">
                    {{ tipoLabel(doc.tipo) }}
                  </span>
                  <div>
                    <p class="text-sm font-medium" style="color: #2C2039;">
                      {{ doc.archivo_nombre || doc.nombre }}
                    </p>
                    <p v-if="doc.notas" class="text-xs" style="color: #9b89b5;">{{ doc.notas }}</p>
                  </div>
                </div>
                <div class="flex items-center gap-2">
                  <a v-if="doc.archivo_url" :href="doc.archivo_url" target="_blank"
                    class="text-xs hover:underline flex items-center gap-1" style="color: #915BD8;">
                    <i class="pi pi-external-link text-xs" /> Ver
                  </a>
                  <button @click="abrirDialogoDocumento(doc)" style="color: #6b5a8a;" class="hover:text-purple-700">
                    <i class="pi pi-pencil text-sm" />
                  </button>
                  <button @click="eliminarDocumento(doc)" class="text-red-400 hover:text-red-600">
                    <i class="pi pi-trash text-sm" />
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- Contratos y Ofertas generales (sin servicio vinculado) -->
          <div v-if="docsComerciales.length > 0">
            <h3 class="text-xs font-bold uppercase tracking-wide mb-2" style="color: #9b89b5;">
              Contratos y Ofertas (generales)
            </h3>
            <div class="space-y-2">
              <div v-for="doc in docsComerciales" :key="doc.id"
                class="flex items-center justify-between rounded-xl px-4 py-3"
                style="border: 1.5px solid #e8e0f0;">
                <div class="flex items-center gap-3">
                  <span class="text-xs font-bold px-2 py-0.5 rounded-full"
                    :style="badgeStyle(doc.tipo)">
                    {{ tipoLabel(doc.tipo) }}
                  </span>
                  <div>
                    <p class="text-sm font-medium" style="color: #2C2039;">{{ doc.nombre }}</p>
                    <p class="text-xs" style="color: #9b89b5;">
                      {{ doc.numero ? `N° ${doc.numero} · ` : '' }}{{ estadoLabel(doc.estado) }}{{ doc.fecha ? ' · ' + formatDate(doc.fecha) : '' }}
                    </p>
                  </div>
                </div>
                <div class="flex items-center gap-2">
                  <a v-if="doc.archivo_url" :href="doc.archivo_url" target="_blank"
                    class="text-xs hover:underline flex items-center gap-1" style="color: #915BD8;">
                    <i class="pi pi-external-link text-xs" /> Ver
                  </a>
                  <button @click="abrirDialogoDocumento(doc)" style="color: #6b5a8a;" class="hover:text-purple-700">
                    <i class="pi pi-pencil text-sm" />
                  </button>
                  <button @click="eliminarDocumento(doc)" class="text-red-400 hover:text-red-600">
                    <i class="pi pi-trash text-sm" />
                  </button>
                </div>
              </div>
            </div>
          </div>

        </div>

      </div>
    </div>
  </div>

  <!-- Loading -->
  <div v-else class="flex items-center justify-center py-20">
    <i class="pi pi-spin pi-spinner text-2xl" style="color: #915BD8;" />
  </div>

  <!-- ── Dialog: Agregar servicio ── -->
  <Dialog v-model:visible="dialogServicio" modal header="Agregar servicio" class="w-full max-w-sm">
    <div class="space-y-4 pt-2">
      <div>
        <label class="block text-xs font-semibold mb-1.5 uppercase tracking-wide" style="color: #2C2039;">
          Tipo de servicio *
        </label>
        <Select v-model="nuevoServicio.tipo" :options="serviciosDisponibles"
          optionLabel="label" optionValue="value" class="w-full" placeholder="Seleccionar" />
      </div>
      <div>
        <label class="block text-xs font-semibold mb-1.5 uppercase tracking-wide" style="color: #2C2039;">
          Fecha de inicio
        </label>
        <DatePicker v-model="nuevoServicio.fecha_inicio" class="w-full" dateFormat="dd/mm/yy" showButtonBar />
      </div>
      <div>
        <label class="block text-xs font-semibold mb-1.5 uppercase tracking-wide" style="color: #2C2039;">Notas</label>
        <Textarea v-model="nuevoServicio.notas" class="w-full" rows="2" />
      </div>
    </div>
    <template #footer>
      <Button label="Cancelar" severity="secondary" @click="dialogServicio = false" />
      <Button label="Confirmar y agregar" :disabled="!nuevoServicio.tipo" @click="confirmarServicio"
        style="background: #915BD8; border-color: #915BD8;" />
    </template>
  </Dialog>

  <!-- ── Dialog: Confirmar agregar servicio ── -->
  <Dialog v-model:visible="dialogConfirmServicio" modal header="¿Está seguro?" class="w-full max-w-sm">
    <div class="py-2 text-sm" style="color: #2C2039;">
      ¿Confirma agregar el servicio
      <strong>{{ servicioLabel(nuevoServicio.tipo) }}</strong>
      al cliente <strong>{{ cliente?.razon_social_nombre }}</strong>?
    </div>
    <template #footer>
      <Button label="Cancelar" severity="secondary" @click="dialogConfirmServicio = false" />
      <Button label="Sí, agregar" @click="guardarServicio"
        style="background: #915BD8; border-color: #915BD8;" />
    </template>
  </Dialog>

  <!-- ── Dialog: Documento ── -->
  <Dialog v-model:visible="dialogDocumento" modal
    :header="editandoDocumento?.id ? 'Editar documento' : 'Nuevo documento'"
    class="w-full max-w-lg">
    <div class="space-y-4 pt-2">
      <div class="grid grid-cols-2 gap-4">

        <!-- Tipo -->
        <div class="col-span-2">
          <label class="block text-xs font-semibold mb-1.5 uppercase tracking-wide" style="color: #2C2039;">Tipo *</label>
          <Select v-model="formDoc.tipo" :options="TIPOS_DOC" optionLabel="label" optionValue="value"
            class="w-full" placeholder="Seleccionar tipo" @change="onTipoChange" />
        </div>

        <!-- Servicio (solo para oferta/contrato) -->
        <div v-if="formDoc.tipo === 'oferta' || formDoc.tipo === 'contrato'" class="col-span-2">
          <label class="block text-xs font-semibold mb-1.5 uppercase tracking-wide" style="color: #2C2039;">
            Servicio relacionado
          </label>
          <Select v-model="formDoc.servicio_id" :options="opcionesServicio" optionLabel="label" optionValue="value"
            class="w-full" placeholder="Seleccionar servicio (opcional)" showClear />
        </div>

        <!-- Nombre -->
        <div class="col-span-2">
          <label class="block text-xs font-semibold mb-1.5 uppercase tracking-wide" style="color: #2C2039;">Nombre *</label>
          <InputText v-model="formDoc.nombre" class="w-full" placeholder="Ej: RUT Empresa XYZ" />
        </div>

        <!-- Estado (solo oferta/contrato) -->
        <template v-if="formDoc.tipo === 'oferta' || formDoc.tipo === 'contrato'">
          <div>
            <label class="block text-xs font-semibold mb-1.5 uppercase tracking-wide" style="color: #2C2039;">Estado</label>
            <Select v-model="formDoc.estado" :options="ESTADOS_DOC" optionLabel="label" optionValue="value" class="w-full" />
          </div>
          <div>
            <label class="block text-xs font-semibold mb-1.5 uppercase tracking-wide" style="color: #2C2039;">Número</label>
            <InputText v-model="formDoc.numero" class="w-full" placeholder="Ej: OFR-001" />
          </div>
          <div>
            <label class="block text-xs font-semibold mb-1.5 uppercase tracking-wide" style="color: #2C2039;">Fecha</label>
            <DatePicker v-model="formDoc.fecha" class="w-full" dateFormat="dd/mm/yy" showButtonBar />
          </div>
          <div />
        </template>

        <!-- Archivo -->
        <div class="col-span-2">
          <label class="block text-xs font-semibold mb-1.5 uppercase tracking-wide" style="color: #2C2039;">
            Archivo (PDF, JPG, PNG — máx. 20 MB)
          </label>
          <div class="flex items-center gap-3">
            <label class="cursor-pointer px-4 py-2 rounded-lg text-sm font-medium text-white flex items-center gap-1.5"
              style="background: #6b5a8a;">
              <i class="pi pi-upload text-xs" />
              {{ archivoSeleccionado ? 'Cambiar' : 'Seleccionar archivo' }}
              <input type="file" accept=".pdf,.jpg,.jpeg,.png,.webp" class="hidden" @change="onArchivoChange" />
            </label>
            <span v-if="archivoSeleccionado" class="text-sm truncate max-w-48" style="color: #2C2039;">
              {{ archivoSeleccionado.name }}
            </span>
            <span v-else-if="formDoc.archivo_nombre" class="text-sm truncate max-w-48" style="color: #9b89b5;">
              Actual: {{ formDoc.archivo_nombre }}
            </span>
          </div>
        </div>

        <!-- URL alternativa -->
        <div class="col-span-2">
          <label class="block text-xs font-semibold mb-1.5 uppercase tracking-wide" style="color: #2C2039;">
            O pega un enlace (Google Drive, OneDrive)
          </label>
          <InputText v-model="formDoc.archivo_url" class="w-full" placeholder="https://drive.google.com/..."
            :disabled="!!archivoSeleccionado" />
        </div>

        <!-- Notas -->
        <div class="col-span-2">
          <label class="block text-xs font-semibold mb-1.5 uppercase tracking-wide" style="color: #2C2039;">Notas</label>
          <Textarea v-model="formDoc.notas" class="w-full" rows="2" />
        </div>

      </div>
    </div>
    <template #footer>
      <Button label="Cancelar" severity="secondary" @click="dialogDocumento = false" />
      <Button label="Guardar" :disabled="!formDoc.tipo || !formDoc.nombre || guardando"
        :loading="guardando" @click="guardarDocumento"
        style="background: #915BD8; border-color: #915BD8;" />
    </template>
  </Dialog>
</template>

<script setup>
import { ref, computed, onMounted, reactive } from 'vue'
import { useRoute } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import Dialog from 'primevue/dialog'
import Button from 'primevue/button'
import Select from 'primevue/select'
import InputText from 'primevue/inputtext'
import Textarea from 'primevue/textarea'
import DatePicker from 'primevue/datepicker'
import api from '@/api/client'
import ClienteForm from './ClienteForm.vue'

const route = useRoute()
const toast = useToast()
const cliente = ref(null)
const activeTab = ref('info')
const guardando = ref(false)
const archivoSeleccionado = ref(null)

const tabs = [
  { key: 'info',       label: 'Información',  icon: 'pi pi-user' },
  { key: 'servicios',  label: 'Servicios',     icon: 'pi pi-briefcase' },
  { key: 'documentos', label: 'Documentos',    icon: 'pi pi-folder' },
]

const SERVICIOS = [
  { value: 'operacion',      label: 'Operación & Mantenimiento' },
  { value: 'representacion', label: 'Representación en mercado' },
  { value: 'cgm',            label: 'CGM' },
  { value: 'promotor',       label: 'Promotor' },
]

const TIPOS_DOC = [
  { value: 'rut',                label: 'RUT' },
  { value: 'certificado_bancario', label: 'Certificado bancario' },
  { value: 'camara_comercio',    label: 'Cámara de comercio' },
  { value: 'oferta',             label: 'Oferta de servicio' },
  { value: 'contrato',           label: 'Contrato de servicio' },
]

const ESTADOS_DOC = [
  { value: 'borrador',  label: 'Borrador' },
  { value: 'enviado',   label: 'Enviado' },
  { value: 'aceptado',  label: 'Aceptado' },
  { value: 'firmado',   label: 'Firmado' },
  { value: 'rechazado', label: 'Rechazado' },
]

const TIPOS_IDENTIFICACION = ['rut', 'certificado_bancario', 'camara_comercio']
const TIPOS_COMERCIAL = ['oferta', 'contrato']

// ── Computed ──────────────────────────────────────────────────────────────────

const docsIdentificacion = computed(() =>
  (cliente.value?.documentos_comerciales || []).filter(d => TIPOS_IDENTIFICACION.includes(d.tipo))
)

const docsComerciales = computed(() =>
  (cliente.value?.documentos_comerciales || [])
    .filter(d => TIPOS_COMERCIAL.includes(d.tipo) && !d.servicio_id)
    .sort((a, b) => (a.tipo === b.tipo ? 0 : a.tipo === 'oferta' ? -1 : 1))
)

const opcionesServicio = computed(() =>
  (cliente.value?.servicios || []).map(s => ({
    label: servicioLabel(s.tipo),
    value: s.id,
  }))
)

function docDeServicio(servicioId, tipo) {
  return (cliente.value?.documentos_comerciales || []).find(
    d => d.servicio_id === servicioId && d.tipo === tipo
  )
}

// ── Servicios ──────────────────────────────────────────────────────────────────

const dialogServicio = ref(false)
const dialogConfirmServicio = ref(false)
const nuevoServicio = reactive({ tipo: '', fecha_inicio: null, notas: '' })

const serviciosDisponibles = computed(() => {
  const existentes = (cliente.value?.servicios || []).map(s => s.tipo)
  return SERVICIOS.filter(s => !existentes.includes(s.value))
})

function abrirDialogoServicio() {
  nuevoServicio.tipo = ''
  nuevoServicio.fecha_inicio = null
  nuevoServicio.notas = ''
  dialogServicio.value = true
}

function confirmarServicio() {
  dialogServicio.value = false
  dialogConfirmServicio.value = true
}

async function guardarServicio() {
  try {
    await api.post(`/clientes/${route.params.id}/servicios`, {
      tipo: nuevoServicio.tipo,
      fecha_inicio: nuevoServicio.fecha_inicio
        ? nuevoServicio.fecha_inicio.toISOString().split('T')[0]
        : null,
      notas: nuevoServicio.notas || null,
    })
    dialogConfirmServicio.value = false
    toast.add({ severity: 'success', summary: 'Servicio agregado', life: 3000 })
    await cargar()
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Error', detail: e.response?.data?.detail, life: 4000 })
  }
}

async function confirmarEliminarServicio(s) {
  if (!confirm(`¿Eliminar el servicio "${servicioLabel(s.tipo)}"?`)) return
  await api.delete(`/clientes/${route.params.id}/servicios/${s.id}`)
  toast.add({ severity: 'success', summary: 'Servicio eliminado', life: 3000 })
  await cargar()
}

// ── Documentos ────────────────────────────────────────────────────────────────

const dialogDocumento = ref(false)
const editandoDocumento = ref(null)
const formDoc = reactive({
  tipo: '', nombre: '', numero: '', fecha: null,
  estado: 'borrador', archivo_url: '', archivo_nombre: '',
  servicio_id: null, notas: '',
})

function abrirDialogoDocumento(doc, tipoPreset = null, servicioPreset = null) {
  editandoDocumento.value = doc
  archivoSeleccionado.value = null
  if (doc) {
    Object.assign(formDoc, {
      ...doc,
      fecha: doc.fecha ? new Date(doc.fecha) : null,
      archivo_url: doc.archivo_url || '',
      archivo_nombre: doc.archivo_nombre || '',
    })
  } else {
    Object.assign(formDoc, {
      tipo: tipoPreset || '',
      nombre: tipoPreset ? nombreSugerido(tipoPreset) : '',
      numero: '', fecha: null, estado: 'borrador',
      archivo_url: '', archivo_nombre: '',
      servicio_id: servicioPreset || null, notas: '',
    })
  }
  dialogDocumento.value = true
}

function onTipoChange() {
  if (!editandoDocumento.value) {
    formDoc.nombre = nombreSugerido(formDoc.tipo)
  }
}

function nombreSugerido(tipo) {
  const labels = {
    rut: 'RUT',
    certificado_bancario: 'Certificado bancario',
    camara_comercio: 'Cámara de comercio',
    oferta: 'Oferta de servicio',
    contrato: 'Contrato de servicio',
  }
  const base = labels[tipo] || ''
  return base ? `${base} — ${cliente.value?.razon_social_nombre || ''}` : ''
}

function onArchivoChange(e) {
  archivoSeleccionado.value = e.target.files[0] || null
  if (archivoSeleccionado.value) {
    formDoc.archivo_url = ''
  }
}

async function guardarDocumento() {
  guardando.value = true
  try {
    const payload = {
      tipo: formDoc.tipo,
      nombre: formDoc.nombre,
      numero: formDoc.numero || null,
      fecha: formDoc.fecha ? new Date(formDoc.fecha).toISOString().split('T')[0] : null,
      estado: formDoc.estado,
      archivo_url: archivoSeleccionado.value ? null : (formDoc.archivo_url || null),
      archivo_nombre: formDoc.archivo_nombre || null,
      servicio_id: formDoc.servicio_id || null,
      notas: formDoc.notas || null,
    }

    let docId
    if (editandoDocumento.value?.id) {
      await api.patch(`/clientes/${route.params.id}/documentos/${editandoDocumento.value.id}`, payload)
      docId = editandoDocumento.value.id
    } else {
      const { data } = await api.post(`/clientes/${route.params.id}/documentos`, payload)
      docId = data.id
    }

    // Upload archivo si se seleccionó uno
    if (archivoSeleccionado.value) {
      const fd = new FormData()
      fd.append('archivo', archivoSeleccionado.value)
      await api.post(`/clientes/${route.params.id}/documentos/${docId}/archivo`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
    }

    dialogDocumento.value = false
    toast.add({ severity: 'success', summary: 'Documento guardado', life: 3000 })
    await cargar()
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Error', detail: e.response?.data?.detail, life: 4000 })
  } finally {
    guardando.value = false
  }
}

async function eliminarDocumento(doc) {
  if (!confirm(`¿Eliminar "${doc.archivo_nombre || doc.nombre}"?`)) return
  await api.delete(`/clientes/${route.params.id}/documentos/${doc.id}`)
  toast.add({ severity: 'success', summary: 'Eliminado', life: 3000 })
  await cargar()
}

// ── Info ──────────────────────────────────────────────────────────────────────

async function saveInfo(payload) {
  await api.patch(`/clientes/${route.params.id}`, payload)
  toast.add({ severity: 'success', summary: 'Información actualizada', life: 3000 })
  await cargar()
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function servicioLabel(tipo) {
  return SERVICIOS.find(s => s.value === tipo)?.label || tipo
}

function servicioColor(tipo) {
  const colors = { operacion: '#915BD8', representacion: '#2C2039', cgm: '#336791', promotor: '#E67E22' }
  return colors[tipo] || '#9b89b5'
}

function tipoLabel(tipo) {
  return TIPOS_DOC.find(t => t.value === tipo)?.label || tipo
}

function estadoLabel(estado) {
  return ESTADOS_DOC.find(e => e.value === estado)?.label || estado
}

function badgeStyle(tipo) {
  const styles = {
    rut:                  'background:#e3f0fd; color:#1976D2',
    certificado_bancario: 'background:#e8f5e9; color:#388E3C',
    camara_comercio:      'background:#fff3e0; color:#F57C00',
    oferta:               'background:#f5f0fb; color:#915BD8',
    contrato:             'background:#e8f5e9; color:#2e7d32',
  }
  return styles[tipo] || 'background:#f3f3f3; color:#555'
}

function formatDate(d) {
  if (!d) return ''
  return new Date(d).toLocaleDateString('es-CO', { day: '2-digit', month: 'short', year: 'numeric' })
}

async function cargar() {
  const { data } = await api.get(`/clientes/${route.params.id}`)
  cliente.value = data
}

onMounted(cargar)
</script>
