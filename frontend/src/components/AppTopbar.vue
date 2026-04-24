<template>
  <header class="h-14 bg-white border-b border-gray-200 flex items-center justify-between px-6 shrink-0">
    <h1 class="text-sm font-semibold text-gray-700">{{ pageTitle }}</h1>
    <Button icon="pi pi-sign-out" severity="secondary" text rounded @click="handleLogout" v-tooltip.left="'Cerrar sesión'" />
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Button from 'primevue/button'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const titles = {
  Dashboard: 'Panel principal',
  Clientes: 'Clientes',
  Proyectos: 'Proyectos',
  ProyectoDetalle: 'Detalle de proyecto',
  Fallas: 'Fallas',
  Liquidaciones: 'Liquidaciones',
}

const pageTitle = computed(() => titles[route.name] || route.name)

function handleLogout() {
  auth.logout()
  router.push('/login')
}
</script>
