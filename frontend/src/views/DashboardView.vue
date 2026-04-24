<template>
  <div class="space-y-6">
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <Card v-for="kpi in kpis" :key="kpi.label" class="shadow-sm">
        <template #content>
          <div class="flex items-center justify-between">
            <div>
              <p class="text-xs text-gray-500 uppercase tracking-wide">{{ kpi.label }}</p>
              <p class="text-2xl font-bold text-gray-800 mt-1">{{ kpi.value ?? '—' }}</p>
            </div>
            <i :class="[kpi.icon, 'text-3xl text-green-400']" />
          </div>
        </template>
      </Card>
    </div>

    <div class="bg-white rounded-xl shadow-sm p-6 text-center text-gray-400 text-sm">
      Bienvenido a la Plataforma de Operaciones de Unergy. Selecciona un módulo en el menú lateral.
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import Card from 'primevue/card'
import api from '@/api/client'

const kpis = ref([
  { label: 'Proyectos', value: null, icon: 'pi pi-bolt' },
  { label: 'Clientes', value: null, icon: 'pi pi-building' },
  { label: 'Fallas abiertas', value: null, icon: 'pi pi-exclamation-triangle' },
  { label: 'Liquidaciones', value: null, icon: 'pi pi-dollar' },
])

onMounted(async () => {
  try {
    const [proy, cli] = await Promise.all([
      api.get('/proyectos?size=1'),
      api.get('/clientes?size=1'),
    ])
    kpis.value[0].value = proy.data.total
    kpis.value[1].value = cli.data.total
  } catch {
    // dashboard degrada graciosamente si falla
  }
})
</script>
