<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-gray-800">Clientes</h2>
      <Button label="Nuevo cliente" icon="pi pi-plus" @click="openNew" />
    </div>

    <div class="bg-white rounded-xl shadow-sm overflow-hidden">
      <div class="p-4 border-b border-gray-100">
        <IconField>
          <InputIcon class="pi pi-search" />
          <InputText v-model="q" placeholder="Buscar por razón social..." class="w-72" @input="onSearch" />
        </IconField>
      </div>

      <DataTable :value="items" lazy :loading="loading" :rows="size" :totalRecords="total"
        paginator @page="onPage" rowHover class="text-sm">
        <Column field="razon_social_nombre" header="Razón social / Nombre" sortable />
        <Column field="nit_cedula" header="NIT / Cédula" />
        <Column field="tipo_persona" header="Tipo" />
        <Column field="ciudad" header="Ciudad" />
        <Column field="correo_electronico" header="Correo" />
        <Column header="Acciones" style="width: 120px">
          <template #body="{ data }">
            <Button icon="pi pi-eye" text rounded size="small" v-tooltip.top="'Ver detalle'" @click="$router.push(`/clientes/${data.id}`)" />
            <Button icon="pi pi-pencil" text rounded size="small" v-tooltip.top="'Editar'" @click="openEdit(data)" />
          </template>
        </Column>
      </DataTable>
    </div>

    <Dialog v-model:visible="dialogVisible" :header="editingId ? 'Editar cliente' : 'Nuevo cliente'"
      modal class="w-full max-w-lg">
      <ClienteForm :initial="form" @save="onSave" @cancel="dialogVisible = false" />
    </Dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import IconField from 'primevue/iconfield'
import InputIcon from 'primevue/inputicon'
import { useToast } from 'primevue/usetoast'
import api from '@/api/client'
import ClienteForm from './ClienteForm.vue'

const toast = useToast()
const items = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const q = ref('')
const loading = ref(false)
const dialogVisible = ref(false)
const editingId = ref(null)
const form = ref({})

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/clientes', { params: { page: page.value, size: size.value, q: q.value || undefined } })
    items.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

onMounted(load)

let searchTimer
function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { page.value = 1; load() }, 350)
}

function onPage(e) {
  page.value = e.page + 1
  load()
}

function openNew() {
  editingId.value = null
  form.value = {}
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  form.value = { ...row }
  dialogVisible.value = true
}

async function onSave(payload) {
  try {
    if (editingId.value) {
      await api.patch(`/clientes/${editingId.value}`, payload)
      toast.add({ severity: 'success', summary: 'Cliente actualizado', life: 3000 })
    } else {
      await api.post('/clientes', payload)
      toast.add({ severity: 'success', summary: 'Cliente creado', life: 3000 })
    }
    dialogVisible.value = false
    load()
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Error', detail: e.response?.data?.detail, life: 4000 })
  }
}
</script>
