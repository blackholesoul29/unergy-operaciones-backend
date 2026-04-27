<template>
  <div v-if="proyecto" class="space-y-6">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <div>
        <Button icon="pi pi-arrow-left" text @click="$router.back()" class="-ml-2 mb-1" />
        <h2 class="text-xl font-bold text-gray-800">{{ proyecto.nombre_comercial }}</h2>
        <Tag :value="proyecto.estado" :severity="estadoSeverity(proyecto.estado)" class="mt-1" />
      </div>
      <Button label="Editar" icon="pi pi-pencil" outlined @click="editMode = !editMode" />
    </div>

    <!-- Tabs -->
    <TabView>
      <TabPanel header="General">
        <div class="grid grid-cols-2 md:grid-cols-3 gap-4 p-4 text-sm">
          <InfoField label="Cliente" :value="proyecto.cliente_id" />
          <InfoField label="Tipo" :value="proyecto.tipo_proyecto" />
          <InfoField label="Tecnología" :value="proyecto.tipo_tecnologia" />
          <InfoField label="Potencia (kWp)" :value="proyecto.potencia_instalada_kwp" />
          <InfoField label="Departamento" :value="proyecto.departamento" />
          <InfoField label="Municipio" :value="proyecto.municipio" />
          <InfoField label="Operador de red" :value="proyecto.operador_red" />
          <InfoField label="Clasificación" :value="proyecto.clasificacion_regulatoria" />
          <InfoField label="Topic slug" :value="proyecto.topic_slug" />
        </div>
      </TabPanel>

      <TabPanel header="Técnico">
        <div class="grid grid-cols-2 md:grid-cols-3 gap-4 p-4 text-sm">
          <InfoField label="Potencia instalada (kWp)" :value="proyecto.potencia_instalada_kwp" />
          <InfoField label="Cantidad de paneles" :value="proyecto.cantidad_total_paneles" />
          <InfoField label="Producción específica (kWh/kWp)" :value="proyecto.produccion_especifica_kwh_kwp" />
        </div>
      </TabPanel>

      <TabPanel header="Inversionistas">
        <div class="p-4 space-y-4">
          <!-- Tabla inversionistas -->
          <DataTable :value="proyecto.inversionistas" class="text-sm" stripedRows>
            <Column field="cliente_nombre" header="Inversionista" />
            <Column header="Participación (%)">
              <template #body="{ data }">
                {{ data.porcentaje_participacion != null ? (data.porcentaje_participacion * 100).toFixed(4) + '%' : '—' }}
              </template>
            </Column>
            <Column header="Patrimonio autónomo">
              <template #body="{ data }">
                <Tag :value="data.es_patrimonio_autonomo ? 'Sí' : 'No'"
                     :severity="data.es_patrimonio_autonomo ? 'info' : 'secondary'" />
              </template>
            </Column>
            <Column header="">
              <template #body="{ data }">
                <Button icon="pi pi-trash" text severity="danger" size="small"
                  @click="eliminarInversionista(data.id)" />
              </template>
            </Column>
            <template #empty>
              <p class="text-center text-gray-400 py-4">Sin inversionistas registrados.</p>
            </template>
          </DataTable>

          <!-- Formulario agregar inversionista -->
          <Divider />
          <p class="font-semibold text-gray-700">Agregar inversionista</p>
          <div class="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
            <div class="flex flex-col gap-1">
              <label class="text-xs text-gray-500">Cliente</label>
              <Select v-model="nuevoInv.cliente_id" :options="clientes"
                optionLabel="razon_social_nombre" optionValue="id"
                placeholder="Seleccionar cliente" filter class="w-full" />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-xs text-gray-500">Porcentaje de participación (%)</label>
              <InputNumber v-model="nuevoInv.porcentaje_pct" :minFractionDigits="2" :maxFractionDigits="7"
                suffix="%" class="w-full" />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-xs text-gray-500">Patrimonio autónomo</label>
              <div class="flex items-center gap-2 h-10">
                <ToggleSwitch v-model="nuevoInv.es_patrimonio_autonomo" />
                <span class="text-sm text-gray-600">{{ nuevoInv.es_patrimonio_autonomo ? 'Sí' : 'No' }}</span>
              </div>
            </div>
          </div>
          <Button label="Agregar" icon="pi pi-plus" :loading="guardando"
            @click="agregarInversionista" class="mt-2" />
        </div>
      </TabPanel>

      <TabPanel header="Servicios">
        <div class="p-4 space-y-3">
          <p class="text-xs text-gray-500 mb-4">Activa o desactiva los servicios contratados para este proyecto.</p>
          <div class="grid grid-cols-2 md:grid-cols-3 gap-3">
            <div v-for="srv in servicios" :key="srv.key"
              class="flex items-center justify-between bg-gray-50 rounded-lg px-4 py-3">
              <span class="text-sm font-medium text-gray-700">{{ srv.label }}</span>
              <ToggleSwitch v-model="srvFlags[srv.key]" @change="toggleServicio(srv.key, srvFlags[srv.key])" />
            </div>
          </div>
        </div>
      </TabPanel>
    </TabView>
  </div>

  <div v-else-if="loading" class="flex justify-center py-20">
    <ProgressSpinner />
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import TabView from 'primevue/tabview'
import TabPanel from 'primevue/tabpanel'
import Tag from 'primevue/tag'
import Button from 'primevue/button'
import ToggleSwitch from 'primevue/toggleswitch'
import ProgressSpinner from 'primevue/progressspinner'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Select from 'primevue/select'
import InputNumber from 'primevue/inputnumber'
import Divider from 'primevue/divider'
import { useToast } from 'primevue/usetoast'
import api from '@/api/client'

const route = useRoute()
const toast = useToast()
const proyecto = ref(null)
const clientes = ref([])
const loading = ref(true)
const editMode = ref(false)
const guardando = ref(false)
const srvFlags = reactive({})

const nuevoInv = reactive({
  cliente_id: null,
  porcentaje_pct: null,
  es_patrimonio_autonomo: false,
})

const servicios = [
  { key: 'srv_operacion', label: 'Operación' },
  { key: 'srv_representacion', label: 'Representación' },
  { key: 'srv_cgm', label: 'CGM' },
  { key: 'srv_ppa', label: 'PPA' },
  { key: 'srv_promotor', label: 'Promotor' },
  { key: 'srv_rec', label: 'REC' },
]

const estadoSeverity = (e) => ({ en_operacion: 'success', en_desarrollo: 'info', suspendido: 'warn', inactivo: 'secondary', terminado: 'secondary' }[e] || 'secondary')

onMounted(async () => {
  try {
    const [proyRes, clientesRes] = await Promise.all([
      api.get(`/proyectos/${route.params.id}`),
      api.get('/clientes?size=200'),
    ])
    proyecto.value = proyRes.data
    clientes.value = clientesRes.data.items
    for (const s of servicios) srvFlags[s.key] = proyRes.data[s.key]
  } finally {
    loading.value = false
  }
})

async function agregarInversionista() {
  if (!nuevoInv.cliente_id) {
    toast.add({ severity: 'warn', summary: 'Selecciona un cliente', life: 2000 })
    return
  }
  guardando.value = true
  try {
    await api.post(`/proyectos/${route.params.id}/inversionistas`, {
      cliente_id: nuevoInv.cliente_id,
      porcentaje_participacion: nuevoInv.porcentaje_pct != null ? nuevoInv.porcentaje_pct / 100 : null,
      es_patrimonio_autonomo: nuevoInv.es_patrimonio_autonomo,
    })
    const { data } = await api.get(`/proyectos/${route.params.id}`)
    proyecto.value = data
    nuevoInv.cliente_id = null
    nuevoInv.porcentaje_pct = null
    nuevoInv.es_patrimonio_autonomo = false
    toast.add({ severity: 'success', summary: 'Inversionista agregado', life: 2000 })
  } catch {
    toast.add({ severity: 'error', summary: 'Error al agregar', life: 3000 })
  } finally {
    guardando.value = false
  }
}

async function eliminarInversionista(invId) {
  try {
    await api.delete(`/proyectos/${route.params.id}/inversionistas/${invId}`)
    proyecto.value.inversionistas = proyecto.value.inversionistas.filter(i => i.id !== invId)
    toast.add({ severity: 'success', summary: 'Inversionista eliminado', life: 2000 })
  } catch {
    toast.add({ severity: 'error', summary: 'Error al eliminar', life: 3000 })
  }
}

async function toggleServicio(key, value) {
  try {
    const { data } = await api.patch(`/proyectos/${route.params.id}/servicios`, { [key]: value })
    proyecto.value = data
    toast.add({ severity: 'success', summary: 'Servicio actualizado', life: 2000 })
  } catch {
    srvFlags[key] = !value
    toast.add({ severity: 'error', summary: 'Error al actualizar', life: 3000 })
  }
}
</script>

<script>
const InfoField = {
  props: { label: String, value: [String, Number, Boolean] },
  template: `<div><p class="text-xs text-gray-400 uppercase tracking-wide">{{ label }}</p><p class="text-gray-800 font-medium mt-0.5">{{ value ?? '—' }}</p></div>`,
}
export default { components: { InfoField } }
</script>
