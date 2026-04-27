<template>
  <form @submit.prevent="submit" class="space-y-5">
    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
      <!-- Proyecto -->
      <div class="sm:col-span-2 flex flex-col gap-1">
        <label class="text-xs font-medium" style="color: #6b5a8a;">Proyecto *</label>
        <Select
          v-model="form.proyecto_id"
          :options="proyectos"
          optionLabel="nombre_comercial"
          optionValue="id"
          placeholder="Seleccionar proyecto"
          filter
          class="w-full"
          :class="{ 'p-invalid': errors.proyecto_id }"
        />
        <small v-if="errors.proyecto_id" class="text-red-500 text-xs">{{ errors.proyecto_id }}</small>
      </div>

      <!-- Tipo -->
      <div class="flex flex-col gap-1">
        <label class="text-xs font-medium" style="color: #6b5a8a;">Tipo de falla *</label>
        <Select
          v-model="form.tipo_id"
          :options="tiposAgrupados"
          optionLabel="etiqueta"
          optionValue="id"
          optionGroupLabel="categoria"
          optionGroupChildren="items"
          placeholder="Seleccionar tipo"
          class="w-full"
          :class="{ 'p-invalid': errors.tipo_id }"
        />
        <small v-if="errors.tipo_id" class="text-red-500 text-xs">{{ errors.tipo_id }}</small>
      </div>

      <!-- Estado -->
      <div class="flex flex-col gap-1">
        <label class="text-xs font-medium" style="color: #6b5a8a;">Estado *</label>
        <Select
          v-model="form.estado_id"
          :options="catalogos.estados"
          optionLabel="etiqueta"
          optionValue="id"
          placeholder="Seleccionar estado"
          class="w-full"
          :class="{ 'p-invalid': errors.estado_id }"
        />
        <small v-if="errors.estado_id" class="text-red-500 text-xs">{{ errors.estado_id }}</small>
      </div>

      <!-- Prioridad -->
      <div class="flex flex-col gap-1">
        <label class="text-xs font-medium" style="color: #6b5a8a;">Prioridad *</label>
        <Select
          v-model="form.prioridad_id"
          :options="catalogos.prioridades"
          optionLabel="etiqueta"
          optionValue="id"
          placeholder="Seleccionar prioridad"
          class="w-full"
          :class="{ 'p-invalid': errors.prioridad_id }"
        />
        <small v-if="errors.prioridad_id" class="text-red-500 text-xs">{{ errors.prioridad_id }}</small>
      </div>

      <!-- Asignado a -->
      <div class="flex flex-col gap-1">
        <label class="text-xs font-medium" style="color: #6b5a8a;">Asignado a</label>
        <Select
          v-model="form.asignado_a_id"
          :options="usuarios"
          optionLabel="nombre"
          optionValue="id"
          placeholder="Sin asignar"
          showClear
          class="w-full"
        />
      </div>

      <!-- Fecha identificación -->
      <div class="flex flex-col gap-1">
        <label class="text-xs font-medium" style="color: #6b5a8a;">Fecha identificación *</label>
        <DatePicker
          v-model="form.fecha_identificacion"
          dateFormat="yy-mm-dd"
          placeholder="AAAA-MM-DD"
          class="w-full"
          :class="{ 'p-invalid': errors.fecha_identificacion }"
        />
        <small v-if="errors.fecha_identificacion" class="text-red-500 text-xs">{{ errors.fecha_identificacion }}</small>
      </div>

      <!-- SLA horas -->
      <div class="flex flex-col gap-1">
        <label class="text-xs font-medium" style="color: #6b5a8a;">SLA límite (horas)</label>
        <InputNumber v-model="form.sla_limite_horas" placeholder="Ej: 24" class="w-full" :min="1" />
      </div>

      <!-- Fecha ocurrencia -->
      <div class="sm:col-span-2 flex flex-col gap-1">
        <label class="text-xs font-medium" style="color: #6b5a8a;">
          Fecha y hora de ocurrencia
          <span style="color: #9b89b5;">(si difiere de la identificación)</span>
        </label>
        <DatePicker
          v-model="form.fecha_ocurrencia"
          dateFormat="yy-mm-dd"
          showTime
          hourFormat="24"
          class="w-full"
          showIcon
        />
      </div>

      <!-- Descripción -->
      <div class="sm:col-span-2 flex flex-col gap-1">
        <label class="text-xs font-medium" style="color: #6b5a8a;">Descripción *</label>
        <Textarea
          v-model="form.descripcion"
          rows="3"
          autoResize
          placeholder="Describe la falla, síntomas observados, equipos afectados..."
          class="w-full"
          :class="{ 'p-invalid': errors.descripcion }"
        />
        <small v-if="errors.descripcion" class="text-red-500 text-xs">{{ errors.descripcion }}</small>
      </div>

      <!-- Nota inicial -->
      <div class="sm:col-span-2 flex flex-col gap-1">
        <label class="text-xs font-medium" style="color: #6b5a8a;">
          Nota inicial
          <span style="color: #9b89b5;">(crea el primer seguimiento automáticamente)</span>
        </label>
        <Textarea
          v-model="form.nota_inicial"
          rows="2"
          autoResize
          placeholder="Ej: Se identificó durante monitoreo remoto..."
          class="w-full"
        />
      </div>
    </div>

    <div class="flex justify-end gap-2 pt-2">
      <Button label="Cancelar" severity="secondary" type="button" @click="$emit('cancel')" />
      <Button
        :label="initial ? 'Guardar cambios' : 'Registrar falla'"
        type="submit"
        :loading="saving"
        style="background: #915BD8; border-color: #915BD8;"
      />
    </div>
  </form>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import Select from 'primevue/select'
import Button from 'primevue/button'
import DatePicker from 'primevue/datepicker'
import InputNumber from 'primevue/inputnumber'
import Textarea from 'primevue/textarea'
import api from '@/api/client'

const props = defineProps({
  initial: { type: Object, default: null },
  catalogos: { type: Object, required: true },
})
const emit = defineEmits(['save', 'cancel'])

const proyectos = ref([])
const usuarios = ref([])
const saving = ref(false)
const errors = ref({})

const form = ref({
  proyecto_id: props.initial?.proyecto_id ?? null,
  tipo_id: props.initial?.tipo?.id ?? null,
  estado_id: props.initial?.estado?.id ?? null,
  prioridad_id: props.initial?.prioridad?.id ?? null,
  asignado_a_id: props.initial?.asignado_a?.id ?? null,
  descripcion: props.initial?.descripcion ?? '',
  fecha_identificacion: props.initial?.fecha_identificacion ? new Date(props.initial.fecha_identificacion) : null,
  fecha_ocurrencia: props.initial?.fecha_ocurrencia ? new Date(props.initial.fecha_ocurrencia) : null,
  sla_limite_horas: props.initial?.sla_limite_horas ?? null,
  nota_inicial: '',
})

const tiposAgrupados = computed(() => {
  const groups = {}
  for (const t of props.catalogos.tipos ?? []) {
    const cat = t.categoria?.etiqueta ?? 'General'
    if (!groups[cat]) groups[cat] = { categoria: cat, items: [] }
    groups[cat].items.push(t)
  }
  return Object.values(groups)
})

function validate() {
  const e = {}
  if (!form.value.proyecto_id) e.proyecto_id = 'Requerido'
  if (!form.value.tipo_id) e.tipo_id = 'Requerido'
  if (!form.value.estado_id) e.estado_id = 'Requerido'
  if (!form.value.prioridad_id) e.prioridad_id = 'Requerido'
  if (!form.value.descripcion?.trim()) e.descripcion = 'Requerido'
  if (!form.value.fecha_identificacion) e.fecha_identificacion = 'Requerido'
  errors.value = e
  return Object.keys(e).length === 0
}

async function submit() {
  if (!validate()) return
  saving.value = true
  try {
    const payload = {
      proyecto_id: form.value.proyecto_id,
      tipo_id: form.value.tipo_id,
      estado_id: form.value.estado_id,
      prioridad_id: form.value.prioridad_id,
      descripcion: form.value.descripcion,
      fecha_identificacion: formatDate(form.value.fecha_identificacion),
    }
    if (form.value.asignado_a_id) payload.asignado_a_id = form.value.asignado_a_id
    if (form.value.sla_limite_horas) payload.sla_limite_horas = form.value.sla_limite_horas
    if (form.value.fecha_ocurrencia) payload.fecha_ocurrencia = form.value.fecha_ocurrencia.toISOString()
    if (form.value.nota_inicial?.trim()) payload.nota_inicial = form.value.nota_inicial.trim()

    emit('save', payload)
  } finally {
    saving.value = false
  }
}

function formatDate(d) {
  if (!d) return null
  if (typeof d === 'string') return d
  return d.toISOString().split('T')[0]
}

onMounted(async () => {
  const [pRes] = await Promise.all([
    api.get('/proyectos', { params: { size: 500 } }),
  ])
  proyectos.value = pRes.data.items ?? []

  try {
    const uData = await api.get('/usuarios', { params: { size: 100 } })
    usuarios.value = uData.data.items ?? []
  } catch {
    // /usuarios may not exist yet
  }
})
</script>
