<template>
  <div class="space-y-6">
    <!-- KPI Cards -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <div
        v-for="kpi in kpis"
        :key="kpi.label"
        class="bg-white rounded-xl shadow-sm p-5 flex items-center justify-between"
        style="border: 1px solid #e8e0f0;"
      >
        <div>
          <p class="text-xs uppercase tracking-wide font-semibold" style="color: #6b5a8a;">{{ kpi.label }}</p>
          <p class="text-3xl font-bold mt-1" style="color: #2C2039;">{{ kpi.value ?? '—' }}</p>
        </div>
        <div class="w-12 h-12 rounded-xl flex items-center justify-center" :style="{ backgroundColor: kpi.bg }">
          <i :class="[kpi.icon, 'text-xl']" :style="{ color: kpi.color }" />
        </div>
      </div>
    </div>

    <!-- Welcome banner -->
    <div class="bg-white rounded-xl shadow-sm p-8 flex flex-col items-center text-center"
         style="border: 1px solid #e8e0f0;">
      <img src="/logos/Logo_lineal_purpura_energico.png" alt="Unergy" class="h-8 w-auto mb-4 opacity-60" />
      <p class="text-sm" style="color: #6b5a8a;">
        Bienvenido a la Plataforma de Operaciones. Selecciona un módulo en el menú lateral.
      </p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '@/api/client'

const kpis = ref([
  { label: 'Proyectos',       value: null, icon: 'pi pi-bolt',                 bg: 'rgba(145,91,216,0.1)', color: '#915BD8' },
  { label: 'Clientes',        value: null, icon: 'pi pi-building',             bg: 'rgba(44,32,57,0.08)',  color: '#2C2039' },
  { label: 'Fallas abiertas', value: null, icon: 'pi pi-exclamation-triangle', bg: 'rgba(246,255,114,0.2)',color: '#8a8a00' },
  { label: 'Liquidaciones',   value: null, icon: 'pi pi-dollar',               bg: 'rgba(145,91,216,0.1)', color: '#915BD8' },
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
