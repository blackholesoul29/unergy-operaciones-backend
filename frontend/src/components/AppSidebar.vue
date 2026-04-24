<template>
  <aside class="w-64 bg-gray-900 text-white flex flex-col shrink-0">
    <div class="px-6 py-5 border-b border-gray-700">
      <span class="text-xl font-bold tracking-tight text-green-400">Unergy</span>
      <span class="text-xs text-gray-400 block">Plataforma Operaciones</span>
    </div>

    <nav class="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
      <RouterLink v-for="item in navItems" :key="item.to" :to="item.to"
        class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-gray-300 hover:bg-gray-700 hover:text-white transition-colors"
        active-class="bg-gray-700 text-white font-semibold">
        <i :class="[item.icon, 'text-base w-5 text-center']" />
        {{ item.label }}
      </RouterLink>
    </nav>

    <div class="px-4 py-4 border-t border-gray-700 text-xs text-gray-500">
      {{ auth.user?.nombre || auth.user?.email }}
      <span class="ml-2 inline-block bg-green-800 text-green-300 px-1.5 rounded text-[10px] uppercase">{{ auth.role }}</span>
    </div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const all = [
  { to: '/dashboard', label: 'Dashboard', icon: 'pi pi-home' },
  { to: '/clientes', label: 'Clientes', icon: 'pi pi-building' },
  { to: '/proyectos', label: 'Proyectos', icon: 'pi pi-bolt' },
  { to: '/fallas', label: 'Fallas', icon: 'pi pi-exclamation-triangle', roles: ['admin', 'operaciones', 'monitoreo'] },
  { to: '/liquidaciones', label: 'Liquidaciones', icon: 'pi pi-dollar', roles: ['admin', 'liquidaciones'] },
]

const navItems = computed(() => all.filter(i => !i.roles || auth.can(...i.roles)))
</script>
