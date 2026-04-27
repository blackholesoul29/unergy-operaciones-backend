<template>
  <div class="space-y-4" v-if="falla">
    <!-- Breadcrumb -->
    <div class="flex items-center gap-2 text-sm">
      <button @click="$router.push('/fallas')"
        class="flex items-center gap-1 hover:underline" style="color: #915BD8;">
        <i class="pi pi-arrow-left text-xs" /> Fallas
      </button>
      <span style="color: #c5b9db;">/</span>
      <span class="font-semibold font-mono" style="color: #2C2039;">{{ falla.codigo_interno }}</span>
    </div>

    <!-- Header card -->
    <div class="bg-white rounded-xl p-5 flex flex-wrap gap-4 items-start justify-between"
      style="border: 1px solid #e8e0f0;">
      <div class="space-y-1 flex-1 min-w-0">
        <div class="flex items-center gap-2 flex-wrap">
          <span class="text-xs px-2.5 py-1 rounded-full font-semibold"
            :style="estadoStyle(falla.estado)">
            {{ falla.estado?.etiqueta }}
          </span>
          <Tag :value="falla.prioridad?.etiqueta" :severity="prioSeverity(falla.prioridad?.nivel)" class="text-xs" />
          <span class="text-xs px-2 py-0.5 rounded-full font-medium"
            :style="{ background: falla.tipo?.categoria?.color_hex + '22', color: falla.tipo?.categoria?.color_hex }">
            {{ falla.tipo?.categoria?.etiqueta }}
          </span>
        </div>
        <p class="text-sm mt-2 leading-relaxed" style="color: #2C2039;">{{ falla.descripcion }}</p>
        <p class="text-xs mt-1" style="color: #9b89b5;">
          {{ falla.proyecto?.nombre_comercial }} · Identificada el {{ formatDate(falla.fecha_identificacion) }}
        </p>
      </div>
      <div class="flex gap-2">
        <Button icon="pi pi-pencil" label="Editar" size="small" severity="secondary" @click="editMode = true" />
        <Button icon="pi pi-trash" size="small" severity="danger" text @click="confirmDelete" />
      </div>
    </div>

    <!-- Editar form inline -->
    <div v-if="editMode" class="bg-white rounded-xl p-5" style="border: 1px solid #e8e0f0;">
      <h3 class="text-sm font-semibold mb-4" style="color: #2C2039;">Editar falla</h3>
      <FallaForm :initial="falla" :catalogos="catalogos" @save="onUpdate" @cancel="editMode = false" />
    </div>

    <!-- Detalle grid -->
    <div v-if="!editMode" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      <InfoField label="Proyecto" :value="falla.proyecto?.nombre_comercial" />
      <InfoField label="Tipo" :value="falla.tipo?.etiqueta" />
      <InfoField label="Registrado por" :value="falla.registrado_por?.nombre" />
      <InfoField label="Asignado a" :value="falla.asignado_a?.nombre ?? '—'" />
      <InfoField label="SLA (horas)" :value="falla.sla_limite_horas?.toString() ?? '—'" />
      <InfoField label="SLA cumplido" :value="slaLabel(falla.sla_cumplido)" />
      <InfoField label="Fecha ocurrencia" :value="formatDatetime(falla.fecha_ocurrencia)" />
      <InfoField label="Fecha resolución" :value="formatDatetime(falla.fecha_resolucion)" />
      <InfoField v-if="falla.resolucion" label="Resolución" :value="falla.resolucion?.etiqueta" />
    </div>

    <!-- Seguimientos -->
    <div class="bg-white rounded-xl p-5" style="border: 1px solid #e8e0f0;">
      <h3 class="text-sm font-semibold mb-4" style="color: #2C2039;">
        <i class="pi pi-list mr-2" style="color: #915BD8;" />Historial de seguimiento
      </h3>

      <!-- Add seguimiento -->
      <div class="mb-5 p-4 rounded-xl space-y-3" style="background: #faf8fd; border: 1px solid #e8e0f0;">
        <div class="flex flex-col gap-1">
          <label class="text-xs font-medium" style="color: #6b5a8a;">Nueva nota</label>
          <Textarea v-model="nuevaNota" rows="2" autoResize placeholder="Escribe una actualización…"
            class="w-full text-sm" />
        </div>
        <div class="flex items-center gap-3">
          <div class="flex flex-col gap-1 flex-1">
            <label class="text-xs font-medium" style="color: #6b5a8a;">Cambiar estado (opcional)</label>
            <Select v-model="nuevoEstadoId" :options="catalogos.estados" optionLabel="etiqueta"
              optionValue="id" placeholder="Mantener estado actual" showClear class="w-full" />
          </div>
          <Button label="Agregar" icon="pi pi-send" :loading="addingSeg"
            :disabled="!nuevaNota.trim() && !nuevoEstadoId"
            style="background: #915BD8; border-color: #915BD8; align-self: flex-end;"
            @click="addSeguimiento" />
        </div>
      </div>

      <!-- Timeline -->
      <div v-if="falla.seguimientos.length === 0"
        class="text-center py-6 text-sm" style="color: #9b89b5;">
        Aún no hay notas de seguimiento.
      </div>

      <div v-else class="relative space-y-4">
        <div class="absolute left-4 top-0 bottom-0 w-px" style="background: #e8e0f0;" />
        <div v-for="seg in sortedSeguimientos" :key="seg.id"
          class="relative flex gap-3 pl-10">
          <div class="absolute left-2 top-1 w-5 h-5 rounded-full flex items-center justify-center text-white text-xs font-bold z-10"
            style="background: #915BD8;">
            {{ seg.usuario.nombre[0].toUpperCase() }}
          </div>
          <div class="flex-1 p-3 rounded-xl text-sm" style="background: #faf8fd; border: 1px solid #e8e0f0;">
            <div class="flex items-start justify-between gap-2 flex-wrap">
              <span class="font-medium" style="color: #2C2039;">{{ seg.usuario.nombre }}</span>
              <span class="text-xs" style="color: #9b89b5;">{{ formatDatetime(seg.created_at) }}</span>
            </div>
            <p v-if="seg.nota" class="mt-1.5 leading-relaxed" style="color: #4a3b6b;">{{ seg.nota }}</p>
            <div v-if="seg.estado_nuevo" class="mt-2 flex items-center gap-1.5 text-xs">
              <i class="pi pi-arrow-right" style="color: #915BD8;" />
              <span class="px-2 py-0.5 rounded-full font-semibold"
                :style="estadoStyle(seg.estado_nuevo)">
                {{ seg.estado_nuevo.etiqueta }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div v-else-if="notFound" class="text-center py-20 text-sm" style="color: #9b89b5;">
    Falla no encontrada.
  </div>

  <div v-else class="flex justify-center py-20">
    <ProgressSpinner />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import { useConfirm } from 'primevue/useconfirm'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Select from 'primevue/select'
import Textarea from 'primevue/textarea'
import ProgressSpinner from 'primevue/progressspinner'
import FallaForm from './FallaForm.vue'
import api from '@/api/client'

const route = useRoute()
const router = useRouter()
const toast = useToast()
const confirm = useConfirm()

const falla = ref(null)
const notFound = ref(false)
const editMode = ref(false)
const addingSeg = ref(false)
const nuevaNota = ref('')
const nuevoEstadoId = ref(null)
const catalogos = ref({ estados: [], prioridades: [], tipos: [], resoluciones: [] })

const sortedSeguimientos = computed(() =>
  [...(falla.value?.seguimientos ?? [])].sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
)

const prioSeverity = (n) => ({ 1: 'danger', 2: 'warn', 3: 'info', 4: 'secondary' }[n] ?? 'secondary')

function estadoStyle(estado) {
  const hex = estado?.color_hex ?? '#915BD8'
  return { background: hex + '22', color: hex }
}

function formatDate(d) {
  if (!d) return '—'
  return new Date(d + 'T00:00:00').toLocaleDateString('es-CO', { day: '2-digit', month: 'short', year: 'numeric' })
}

function formatDatetime(d) {
  if (!d) return '—'
  return new Date(d).toLocaleString('es-CO', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function slaLabel(v) {
  if (v === null || v === undefined) return '—'
  return v ? 'Cumplido' : 'Incumplido'
}

async function load() {
  try {
    const { data } = await api.get(`/fallas/${route.params.id}`)
    falla.value = data
  } catch (err) {
    if (err?.response?.status === 404) notFound.value = true
  }
}

async function loadCatalogos() {
  try {
    const { data } = await api.get('/fallas/catalogos')
    catalogos.value = data
  } catch { /* keep defaults */ }
}

async function onUpdate(payload) {
  try {
    await api.patch(`/fallas/${falla.value.id}`, payload)
    toast.add({ severity: 'success', summary: 'Falla actualizada', life: 3000 })
    editMode.value = false
    load()
  } catch (err) {
    const msg = err?.response?.data?.detail ?? 'Error al actualizar'
    toast.add({ severity: 'error', summary: 'Error', detail: msg, life: 4000 })
  }
}

async function addSeguimiento() {
  if (!nuevaNota.value.trim() && !nuevoEstadoId.value) return
  addingSeg.value = true
  try {
    const payload = {}
    if (nuevaNota.value.trim()) payload.nota = nuevaNota.value.trim()
    if (nuevoEstadoId.value) payload.estado_nuevo_id = nuevoEstadoId.value
    await api.post(`/fallas/${falla.value.id}/seguimientos`, payload)
    nuevaNota.value = ''
    nuevoEstadoId.value = null
    toast.add({ severity: 'success', summary: 'Seguimiento agregado', life: 2500 })
    load()
  } catch (err) {
    const msg = err?.response?.data?.detail ?? 'Error al agregar seguimiento'
    toast.add({ severity: 'error', summary: 'Error', detail: msg, life: 4000 })
  } finally {
    addingSeg.value = false
  }
}

function confirmDelete() {
  confirm.require({
    message: `¿Eliminar la falla ${falla.value.codigo_interno}? Esta acción no se puede deshacer.`,
    header: 'Confirmar eliminación',
    icon: 'pi pi-exclamation-triangle',
    rejectProps: { label: 'Cancelar', severity: 'secondary' },
    acceptProps: { label: 'Eliminar', severity: 'danger' },
    accept: async () => {
      try {
        await api.delete(`/fallas/${falla.value.id}`)
        toast.add({ severity: 'success', summary: 'Falla eliminada', life: 3000 })
        router.push('/fallas')
      } catch {
        toast.add({ severity: 'error', summary: 'Error al eliminar', life: 3000 })
      }
    },
  })
}

onMounted(() => {
  loadCatalogos()
  load()
})
</script>
