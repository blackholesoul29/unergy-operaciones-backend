<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-gray-800">Liquidaciones</h2>
      <Button label="Nueva liquidación" icon="pi pi-plus" @click="openNew" />
    </div>

    <div class="bg-white rounded-xl shadow-sm overflow-hidden">
      <DataTable :value="items" lazy :loading="loading" :rows="size" :totalRecords="total"
        paginator @page="onPage" rowHover class="text-sm">
        <Column field="periodo" header="Período" style="width:120px" />
        <Column field="proyecto_id" header="Proyecto" />
        <Column header="Estado">
          <template #body="{ data }">
            <Tag :value="data.estado" :severity="estadoSeverity(data.estado)" />
          </template>
        </Column>
        <Column field="ingresos_totales_cop" header="Ingresos (COP)" />
        <Column field="fecha_firma" header="Fecha firma" />
        <Column field="responsable_id" header="Responsable" />
      </DataTable>
    </div>

    <Dialog v-model:visible="dialogVisible" header="Nueva liquidación" modal class="w-full max-w-lg">
      <p class="text-sm text-gray-500 py-4 text-center">Módulo de liquidaciones — próximamente.</p>
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

const estadoSeverity = (e) => ({
  iniciada: 'secondary', en_proceso: 'info', revision_interna: 'warn',
  enviada_cliente: 'warn', aprobada: 'success', facturada: 'success',
  mandato_generado: 'success', entregado: 'contrast',
}[e] || 'secondary')

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/liquidaciones', { params: { page: page.value, size: size.value } })
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
