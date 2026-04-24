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
import { useToast } from 'primevue/usetoast'
import api from '@/api/client'

const route = useRoute()
const toast = useToast()
const proyecto = ref(null)
const loading = ref(true)
const editMode = ref(false)
const srvFlags = reactive({})

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
    const { data } = await api.get(`/proyectos/${route.params.id}`)
    proyecto.value = data
    for (const s of servicios) srvFlags[s.key] = data[s.key]
  } finally {
    loading.value = false
  }
})

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
