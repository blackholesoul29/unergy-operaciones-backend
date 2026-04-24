<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-gray-800">Proyectos</h2>
      <Button label="Nuevo proyecto" icon="pi pi-plus" @click="openNew" />
    </div>

    <!-- Filtros -->
    <div class="bg-white rounded-xl shadow-sm p-4 flex flex-wrap gap-3 items-end">
      <div>
        <label class="field-label">Buscar</label>
        <IconField>
          <InputIcon class="pi pi-search" />
          <InputText v-model="filters.q" placeholder="Nombre comercial…" class="w-56" @input="onSearch" />
        </IconField>
      </div>
      <div>
        <label class="field-label">Estado</label>
        <Select v-model="filters.estado" :options="estados" class="w-40" placeholder="Todos" showClear @change="load" />
      </div>
      <div>
        <label class="field-label">Tipo</label>
        <Select v-model="filters.tipo_proyecto" :options="tipos" class="w-44" placeholder="Todos" showClear @change="load" />
      </div>
    </div>

    <div class="bg-white rounded-xl shadow-sm overflow-hidden">
      <DataTable :value="items" lazy :loading="loading" :rows="size" :totalRecords="total"
        paginator @page="onPage" rowHover selectionMode="single" @rowSelect="goDetail" class="text-sm">
        <Column field="nombre_comercial" header="Nombre comercial" sortable />
        <Column field="estado" header="Estado">
          <template #body="{ data }">
            <Tag :value="data.estado" :severity="estadoSeverity(data.estado)" />
          </template>
        </Column>
        <Column field="tipo_proyecto" header="Tipo" />
        <Column field="potencia_instalada_kwp" header="kWp" />
        <Column field="departamento" header="Depto." />
        <Column header="Servicios" style="width:160px">
          <template #body="{ data }">
            <div class="flex gap-1 flex-wrap">
              <span v-if="data.srv_operacion" class="srv-badge">OP</span>
              <span v-if="data.srv_representacion" class="srv-badge">REP</span>
              <span v-if="data.srv_cgm" class="srv-badge">CGM</span>
              <span v-if="data.srv_ppa" class="srv-badge">PPA</span>
              <span v-if="data.srv_promotor" class="srv-badge">PROM</span>
              <span v-if="data.srv_rec" class="srv-badge">REC</span>
            </div>
          </template>
        </Column>
      </DataTable>
    </div>

    <Dialog v-model:visible="dialogVisible" header="Nuevo proyecto" modal class="w-full max-w-xl">
      <ProyectoForm :clientes="clientes" @save="onCreate" @cancel="dialogVisible = false" />
    </Dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, reactive } from 'vue'
import { useRouter } from 'vue-router'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import Tag from 'primevue/tag'
import IconField from 'primevue/iconfield'
import InputIcon from 'primevue/inputicon'
import { useToast } from 'primevue/usetoast'
import api from '@/api/client'
import ProyectoForm from './ProyectoForm.vue'

const router = useRouter()
const toast = useToast()

const items = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const loading = ref(false)
const dialogVisible = ref(false)
const clientes = ref([])

const filters = reactive({ q: '', estado: null, tipo_proyecto: null })

const estados = ['en_desarrollo', 'en_operacion', 'suspendido', 'inactivo', 'terminado']
const tipos = ['autogeneracion', 'autoconsumo', 'gd_mercado', 'estandar']

const estadoSeverity = (e) => ({ en_operacion: 'success', en_desarrollo: 'info', suspendido: 'warn', inactivo: 'secondary', terminado: 'secondary' }[e] || 'secondary')

async function load() {
  loading.value = true
  try {
    const params = { page: page.value, size: size.value }
    if (filters.q) params.q = filters.q
    if (filters.estado) params.estado = filters.estado
    if (filters.tipo_proyecto) params.tipo_proyecto = filters.tipo_proyecto
    const { data } = await api.get('/proyectos', { params })
    items.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

async function loadClientes() {
  const { data } = await api.get('/clientes', { params: { size: 200 } })
  clientes.value = data.items
}

onMounted(() => { load(); loadClientes() })

let searchTimer
function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { page.value = 1; load() }, 350)
}

function onPage(e) { page.value = e.page + 1; load() }
function goDetail(e) { router.push(`/proyectos/${e.data.id}`) }
function openNew() { dialogVisible.value = true }

async function onCreate(payload) {
  try {
    await api.post('/proyectos', payload)
    toast.add({ severity: 'success', summary: 'Proyecto creado', life: 3000 })
    dialogVisible.value = false
    load()
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Error', detail: e.response?.data?.detail, life: 4000 })
  }
}
</script>

<style scoped>
.field-label { @apply block text-xs font-medium text-gray-600 mb-1; }
.srv-badge { @apply bg-green-100 text-green-800 text-[10px] font-semibold px-1.5 py-0.5 rounded; }
</style>
