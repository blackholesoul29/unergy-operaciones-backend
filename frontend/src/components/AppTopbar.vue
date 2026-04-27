<template>
  <header class="h-14 bg-white border-b flex items-center justify-between px-6 shrink-0" style="border-color: #e8e0f0;">
    <h1 class="text-sm font-semibold" style="color: #2C2039;">{{ pageTitle }}</h1>

    <div class="flex items-center gap-3">
      <span class="text-xs hidden sm:block" style="color: #6b5a8a;">{{ auth.user?.email }}</span>
      <button
        @click="handleLogout"
        class="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-colors"
        style="color: #915BD8; border: 1px solid #915BD8;"
        onmouseover="this.style.backgroundColor='#915BD8';this.style.color='#FDFAF7'"
        onmouseout="this.style.backgroundColor='transparent';this.style.color='#915BD8'"
        title="Cerrar sesión"
      >
        <i class="pi pi-sign-out text-xs" />
        <span class="hidden sm:inline">Salir</span>
      </button>
    </div>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const titles = {
  Dashboard:       'Panel principal',
  Clientes:        'Clientes',
  Proyectos:       'Proyectos',
  ProyectoDetalle: 'Detalle de proyecto',
  Fallas:          'Fallas',
  FallaDetalle:    'Detalle de falla',
  Liquidaciones:   'Liquidaciones',
}

const pageTitle = computed(() => titles[route.name] || route.name)

function handleLogout() {
  auth.logout()
  router.push('/login')
}
</script>
