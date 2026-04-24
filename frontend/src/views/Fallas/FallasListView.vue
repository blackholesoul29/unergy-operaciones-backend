<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-gray-800">Fallas</h2>
      <Button label="Registrar falla" icon="pi pi-plus" @click="openNew" />
    </div>

    <div class="bg-white rounded-xl shadow-sm overflow-hidden">
      <DataTable :value="items" lazy :loading="loading" :rows="size" :totalRecords="total"
        paginator @page="onPage" rowHover class="text-sm">
        <Column field="codigo_interno" header="Código" style="width:120px" />
        <Column field="fecha_identificacion" header="Fecha" />
        <Column header="Estado">
          <template #body="{ data }">
            <Tag :value="data.estado?.nombre || data.estado_id" />
          </template>
        </Column>
        <Column header="Prioridad">
          <template #body="{ data }">
            <Tag :value="data.prioridad?.nombre || data.prioridad_id" :severity="prioSeverity(data.prioridad?.nivel)" />
          </template>
        </Column>
        <Column field="descripcion" header="Descripción" />
        <Column field="asignado_a_id" header="Asignado a" />
      </DataTable>
    </div>

    <Dialog v-model:visible="dialogVisible" header="Registrar falla" modal class="w-full max-w-lg">
      <p class="text-sm text-gray-500 py-4 text-center">Formulario de fallas — próximamente.</p>
      <div class="flex justify-end">
        <Button label="Cerrar" severity="secondary" @click="dialogVisible = false" />
      </div>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import Tag from 'primevue/tag'
import api from '@/api/client'

const items = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const loading = ref(false)
const dialogVisible = ref(false)

const prioSeverity = (n) => ({ 1: 'danger', 2: 'warn', 3: 'info', 4: 'secondary' }[n] || 'secondary')

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/fallas', { params: { page: page.value, size: size.value } })
    items.value = data.items
    total.value = data.total
  } catch {
    items.value = []
  } finally {
    loading.value = false
  }
}

onMounted(load)
function onPage(e) { page.value = e.page + 1; load() }
function openNew() { dialogVisible.value = true }
</script>
