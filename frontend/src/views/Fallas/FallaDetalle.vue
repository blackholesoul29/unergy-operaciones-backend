<template>
  <div class="flex flex-col h-full space-y-4 overflow-y-auto pb-6">

    <!-- Status strip -->
    <div class="flex items-center gap-2 flex-wrap">
      <Tag :value="falla.estado?.etiqueta" :style="tagStyle(falla.estado)" />
      <Tag v-if="falla.prioridad" :value="falla.prioridad?.etiqueta" :style="prioTagStyle(falla.prioridad)" />
      <span class="text-xs font-bold ml-auto" :style="{ color: diasColor(falla.dias_abierta) }">
        {{ falla.dias_abierta ?? '—' }} días abierta
      </span>
    </div>

    <!-- Info principal -->
    <div class="rounded-xl border p-4 space-y-3" style="border-color:#e8e0f0;">
      <div class="grid grid-cols-2 gap-3">
        <div>
          <p class="field-label">Proyecto</p>
          <p class="text-sm font-semibold" style="color:#2C2039;">{{ proyectoNombre }}</p>
        </div>
        <div>
          <p class="field-label">Tipo de falla</p>
          <p class="text-sm font-semibold" style="color:#2C2039;">
            {{ falla.tipo_falla?.codigo }} · {{ falla.tipo_falla?.etiqueta || '—' }}
          </p>
        </div>
        <div>
          <p class="field-label">Fecha identificación</p>
          <p class="text-sm" style="color:#2C2039;">{{ fmtDate(falla.fecha_identificacion) }}</p>
        </div>
        <div>
          <p class="field-label">Hora</p>
          <p class="text-sm" style="color:#2C2039;">{{ fmtTime(falla.hora_identificacion) }}</p>
        </div>
        <div v-if="falla.fecha_resolucion" class="col-span-2">
          <p class="field-label">Fecha resolución</p>
          <p class="text-sm" style="color:#10B981;">{{ fmtDate(falla.fecha_resolucion) }}</p>
        </div>
      </div>

      <div v-if="falla.descripcion">
        <p class="field-label">Descripción</p>
        <p class="text-sm leading-relaxed" style="color:#2C2039;">{{ falla.descripcion }}</p>
      </div>

      <div v-if="falla.tipo_resolucion">
        <p class="field-label">Tipo de resolución</p>
        <p class="text-sm" style="color:#2C2039;">{{ falla.tipo_resolucion?.etiqueta }}</p>
      </div>

      <div v-if="falla.causa_raiz">
        <p class="field-label">Causa raíz</p>
        <p class="text-sm" style="color:#2C2039;">{{ falla.causa_raiz }}</p>
      </div>

      <div v-if="falla.energia_perdida_kwh != null">
        <p class="field-label">Energía perdida estimada</p>
        <p class="text-sm font-bold" style="color:#EF4444;">
          {{ falla.energia_perdida_kwh.toLocaleString('es-CO') }} kWh
        </p>
      </div>
    </div>

    <!-- Acción sugerida del catálogo -->
    <div v-if="falla.tipo_falla?.accion_sugerida"
         class="rounded-xl border-l-4 px-4 py-3 text-sm"
         style="border-color:#915BD8;background:#f9f6fe;color:#4b3b72;">
      <p class="text-[10px] font-bold uppercase tracking-wide mb-1" style="color:#915BD8;">
        Acción sugerida
      </p>
      {{ falla.tipo_falla.accion_sugerida }}
    </div>

    <!-- SLA barra -->
    <div class="rounded-xl border p-3" style="border-color:#e8e0f0;">
      <div class="flex justify-between text-xs mb-2">
        <span style="color:#9b89b5;">SLA — {{ falla.sla_limite_dias ?? 7 }} días máx.</span>
        <span class="font-bold" :style="{ color: slaColor }">{{ slaLabel }}</span>
      </div>
      <div class="h-2 rounded-full" style="background:#f0eaf8;">
        <div class="h-2 rounded-full transition-all duration-500" :style="slaBarStyle" />
      </div>
    </div>

    <!-- Edición rápida de estado -->
    <div class="rounded-xl border p-4 space-y-3" style="border-color:#e8e0f0;">
      <p class="text-xs font-bold uppercase tracking-wide" style="color:#915BD8;">Actualizar estado</p>
      <div class="grid grid-cols-2 gap-2">
        <div>
          <label class="field-label">Estado</label>
          <Select v-model="editState.estado_id" :options="catalogos.estados"
                  option-value="id" option-label="etiqueta" class="w-full" />
        </div>
        <div>
          <label class="field-label">Prioridad</label>
          <Select v-model="editState.prioridad_id" :options="catalogos.prioridades"
                  option-value="id" option-label="etiqueta" class="w-full" />
        </div>
        <div>
          <label class="field-label">Tipo resolución</label>
          <Select v-model="editState.tipo_resolucion_id" :options="catalogos.resoluciones"
                  option-value="id" option-label="etiqueta" class="w-full" show-clear />
        </div>
        <div>
          <label class="field-label">Energía perdida (kWh)</label>
          <InputNumber v-model="editState.energia_perdida_kwh" class="w-full"
                       :min-fraction-digits="0" :max-fraction-digits="1" />
        </div>
      </div>
      <div>
        <label class="field-label">Causa raíz</label>
        <Textarea v-model="editState.causa_raiz" rows="2" class="w-full"
                  placeholder="Describe la causa raíz identificada…" />
      </div>
      <div class="flex justify-end">
        <Button label="Guardar cambios" icon="pi pi-check" size="small"
                :loading="saving" @click="saveEdit" />
      </div>
    </div>

    <!-- Fotos -->
    <div class="rounded-xl border p-4 space-y-3" style="border-color:#e8e0f0;">
      <div class="flex items-center justify-between">
        <p class="text-xs font-bold uppercase tracking-wide" style="color:#915BD8;">
          Fotos ({{ falla.fotos?.length || 0 }})
        </p>
        <label class="cursor-pointer text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors"
               style="background:#f0eaf8;color:#915BD8;">
          <i class="pi pi-upload mr-1" /> Subir
          <input type="file" class="hidden" accept="image/*,.pdf"
                 multiple @change="uploadFotos" />
        </label>
      </div>

      <div v-if="falla.fotos?.length" class="grid grid-cols-3 gap-2">
        <div v-for="foto in falla.fotos" :key="foto.id"
             class="relative group rounded-lg overflow-hidden border aspect-square"
             style="border-color:#e8e0f0;">
          <img v-if="isImage(foto.url)" :src="foto.url" :alt="foto.nombre_archivo"
               class="w-full h-full object-cover" />
          <div v-else class="w-full h-full flex flex-col items-center justify-center"
               style="background:#f5f0fb;">
            <i class="pi pi-file-pdf text-2xl" style="color:#915BD8;" />
            <span class="text-[9px] mt-1 text-center px-1 truncate w-full text-center"
                  style="color:#9b89b5;">{{ foto.nombre_archivo }}</span>
          </div>
          <!-- Overlay delete -->
          <div class="absolute inset-0 bg-black bg-opacity-50 opacity-0 group-hover:opacity-100
                      transition-opacity flex items-center justify-center gap-2">
            <a :href="foto.url" target="_blank"
               class="p-1.5 rounded-lg bg-white text-xs" style="color:#2C2039;"
               title="Ver">
              <i class="pi pi-eye" />
            </a>
            <button class="p-1.5 rounded-lg bg-red-500 text-white text-xs"
                    title="Eliminar" @click="deleteFoto(foto)">
              <i class="pi pi-trash" />
            </button>
          </div>
          <span v-if="foto.etapa"
                class="absolute top-1 left-1 text-[9px] font-bold px-1.5 py-0.5 rounded"
                style="background:#2C2039;color:#fff;opacity:.85;">
            {{ foto.etapa }}
          </span>
        </div>
      </div>
      <p v-else class="text-xs text-center py-3" style="color:#9b89b5;">
        Sin fotos adjuntas
      </p>
    </div>

    <!-- Seguimientos -->
    <div class="rounded-xl border p-4 space-y-3" style="border-color:#e8e0f0;">
      <p class="text-xs font-bold uppercase tracking-wide" style="color:#915BD8;">
        Seguimiento ({{ falla.seguimientos?.length || 0 }})
      </p>

      <div class="space-y-3 max-h-64 overflow-y-auto pr-1">
        <div v-for="seg in [...(falla.seguimientos || [])].reverse()" :key="seg.id"
             class="border-l-2 pl-3 py-1" style="border-color:#e0d4f5;">
          <div class="flex items-center gap-2 mb-1">
            <span class="text-[10px] font-bold" style="color:#915BD8;">
              {{ seg.usuario_nombre || 'Sistema' }}
            </span>
            <span class="text-[10px]" style="color:#9b89b5;">
              {{ fmtDateTime(seg.created_at) }}
            </span>
            <Tag v-if="seg.estado_nuevo" :value="seg.estado_nuevo"
                 class="text-[9px] ml-auto" style="font-size:9px;" />
          </div>
          <p class="text-xs leading-relaxed" style="color:#2C2039;">{{ seg.nota }}</p>
        </div>
        <p v-if="!falla.seguimientos?.length"
           class="text-xs text-center py-2" style="color:#9b89b5;">
          Sin seguimientos aún
        </p>
      </div>

      <!-- Nueva nota -->
      <div class="space-y-2 pt-2 border-t" style="border-color:#f0eaf8;">
        <div class="grid grid-cols-2 gap-2">
          <div>
            <label class="field-label">Nuevo estado <span style="color:#9b89b5;">(opcional)</span></label>
            <Select v-model="newSeg.estado_nuevo" :options="catalogos.estados"
                    option-value="codigo" option-label="etiqueta"
                    class="w-full" placeholder="Sin cambio" show-clear />
          </div>
        </div>
        <Textarea v-model="newSeg.nota" rows="2" class="w-full"
                  placeholder="Escribe la actualización o novedad…" />
        <div class="flex justify-end">
          <Button label="Agregar nota" icon="pi pi-plus" size="small"
                  :disabled="!newSeg.nota.trim()" :loading="segLoading"
                  @click="addSeguimiento" />
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Select from 'primevue/select'
import Textarea from 'primevue/textarea'
import InputNumber from 'primevue/inputnumber'
import { useToast } from 'primevue/usetoast'
import api from '@/api/client'

const props  = defineProps({ falla: Object, catalogos: Object })
const emit   = defineEmits(['update', 'close'])
const toast  = useToast()

// ── edit state ────────────────────────────────────────────────
const editState = reactive({
  estado_id:          props.falla.estado_id,
  prioridad_id:       props.falla.prioridad_id,
  tipo_resolucion_id: props.falla.tipo_resolucion_id,
  causa_raiz:         props.falla.causa_raiz || '',
  energia_perdida_kwh:props.falla.energia_perdida_kwh,
})
const saving = ref(false)

const newSeg = reactive({ nota: '', estado_nuevo: null })
const segLoading = ref(false)

// ── computed ──────────────────────────────────────────────────
const proyectoNombre = computed(() =>
  props.falla.proyecto?.nombre_display ||
  props.falla.proyecto?.nombre_clientes ||
  props.falla.proyecto_nombre_raw || '—'
)

const slaLabel = computed(() => {
  const f = props.falla
  if (!f.sla_limite_dias || f.dias_abierta == null) return '—'
  const pct = Math.round(f.dias_abierta / f.sla_limite_dias * 100)
  if (f.estado?.es_terminal) return f.sla_cumplido ? '✅ Cumplido' : '❌ Excedió'
  return pct > 100 ? `❌ ${pct}% del límite` : `${pct}% del límite`
})

const slaColor = computed(() => {
  const f = props.falla
  if (!f.sla_limite_dias || f.dias_abierta == null) return '#9b89b5'
  const pct = f.dias_abierta / f.sla_limite_dias * 100
  return pct >= 100 ? '#EF4444' : pct >= 70 ? '#F59E0B' : '#10B981'
})

const slaBarStyle = computed(() => {
  const f = props.falla
  if (!f.sla_limite_dias || f.dias_abierta == null) return 'width:0%'
  const pct = Math.min(f.dias_abierta / f.sla_limite_dias * 100, 100)
  const bg = pct >= 100 ? '#EF4444' : pct >= 70 ? '#F59E0B' : '#10B981'
  return `width:${pct}%;background:${bg}`
})

// ── helpers visuales ──────────────────────────────────────────
const tagStyle = (e) => {
  if (!e) return 'background:#f3f4f6;color:#6b7280;border:none'
  const m = { activa:'background:#FEF2F2;color:#EF4444;border:1px solid #FECACA',
              en_revision:'background:#FFFBEB;color:#B45309;border:1px solid #FDE68A',
              programada:'background:#EFF6FF;color:#2563EB;border:1px solid #BFDBFE',
              terminada:'background:#F0FDF4;color:#15803D;border:1px solid #BBF7D0' }
  return m[e.codigo] || 'background:#f3f4f6;color:#6b7280;border:none'
}
const prioTagStyle = (p) => {
  if (!p) return 'background:#f3f4f6;color:#6b7280;border:none'
  const m = { critica:'background:#FEF2F2;color:#DC2626;border:1px solid #FECACA',
              alta:'background:#FFFBEB;color:#B45309;border:1px solid #FDE68A',
              media:'background:#EFF6FF;color:#1D4ED8;border:1px solid #BFDBFE',
              baja:'background:#F9FAFB;color:#6B7280;border:1px solid #E5E7EB' }
  return m[p.codigo] || 'background:#f3f4f6;color:#6b7280;border:none'
}
const diasColor = (d) => !d ? '#9b89b5' : d >= 7 ? '#EF4444' : d >= 4 ? '#F59E0B' : '#10B981'
const fmtDate = (d) => d ? new Date(d).toLocaleDateString('es-CO', { day:'2-digit', month:'short', year:'numeric' }) : '—'
const fmtTime = (t) => t ? String(t).slice(0, 5) : '—'
const fmtDateTime = (d) => d ? new Date(d).toLocaleString('es-CO', { day:'2-digit', month:'short', hour:'2-digit', minute:'2-digit' }) : '—'
const isImage = (url) => /\.(jpg|jpeg|png|gif|webp)$/i.test(url || '')

// ── acciones ──────────────────────────────────────────────────
async function saveEdit() {
  saving.value = true
  try {
    const { data } = await api.patch(`/fallas/${props.falla.id}`, editState)
    toast.add({ severity: 'success', summary: 'Falla actualizada', life: 2500 })
    emit('update', data)
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Error', detail: e.response?.data?.detail, life: 3000 })
  } finally {
    saving.value = false
  }
}

async function addSeguimiento() {
  if (!newSeg.nota.trim()) return
  segLoading.value = true
  try {
    await api.post(`/fallas/${props.falla.id}/seguimientos`, {
      nota: newSeg.nota.trim(),
      estado_nuevo: newSeg.estado_nuevo || null,
    })
    const { data } = await api.get(`/fallas/${props.falla.id}`)
    newSeg.nota = ''
    newSeg.estado_nuevo = null
    emit('update', data)
    toast.add({ severity: 'success', summary: 'Seguimiento guardado', life: 2000 })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Error', detail: e.response?.data?.detail, life: 3000 })
  } finally {
    segLoading.value = false
  }
}

async function uploadFotos(event) {
  const files = Array.from(event.target.files)
  if (!files.length) return
  for (const file of files) {
    const form = new FormData()
    form.append('file', file)
    form.append('etapa', 'proceso')
    try {
      await api.post(`/fallas/${props.falla.id}/fotos`, form, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
    } catch {
      toast.add({ severity: 'warn', summary: `No se pudo subir ${file.name}`, life: 3000 })
    }
  }
  const { data } = await api.get(`/fallas/${props.falla.id}`)
  emit('update', data)
  toast.add({ severity: 'success', summary: `${files.length} foto(s) subidas`, life: 2000 })
  event.target.value = ''
}

async function deleteFoto(foto) {
  try {
    await api.delete(`/fallas/${props.falla.id}/fotos/${foto.id}`)
    const { data } = await api.get(`/fallas/${props.falla.id}`)
    emit('update', data)
  } catch {
    toast.add({ severity: 'error', summary: 'No se pudo eliminar la foto', life: 3000 })
  }
}
</script>

<style scoped>
.field-label { @apply block text-[10px] font-semibold uppercase tracking-wide mb-1; color: #9b89b5; }
</style>
