<template>
  <aside class="w-64 flex flex-col shrink-0" style="background-color: #2C2039;">
    <!-- Logo -->
    <div class="px-6 py-5 flex flex-col items-start border-b" style="border-color: rgba(255,255,255,0.08);">
      <img src="/logos/Logo_avena.png" alt="Unergy" class="h-7 w-auto object-contain" />
      <span class="text-xs mt-1.5" style="color: rgba(253,250,247,0.45);">Plataforma Operaciones</span>
    </div>

    <!-- Nav -->
    <nav class="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
      <RouterLink
        v-for="item in navItems"
        :key="item.to"
        :to="item.to"
        class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all duration-150 nav-item"
        active-class="nav-active"
      >
        <i :class="[item.icon, 'text-base w-5 text-center shrink-0']" />
        {{ item.label }}
      </RouterLink>
    </nav>

    <!-- User footer -->
    <div class="px-4 py-4 border-t" style="border-color: rgba(255,255,255,0.08);">
      <div class="flex items-center gap-2.5">
        <div class="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
             style="background-color: #915BD8; color: #FDFAF7;">
          {{ initials }}
        </div>
        <div class="min-w-0">
          <p class="text-xs font-medium truncate" style="color: #FDFAF7;">{{ auth.user?.nombre || auth.user?.email }}</p>
          <span class="text-[10px] uppercase tracking-wide" style="color: #915BD8;">{{ auth.role }}</span>
        </div>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const initials = computed(() => {
  const name = auth.user?.nombre || auth.user?.email || ''
  return name.split(' ').slice(0, 2).map(w => w[0]).join('').toUpperCase()
})

const all = [
  { to: '/dashboard',     label: 'Dashboard',     icon: 'pi pi-home' },
  { to: '/clientes',      label: 'Clientes',       icon: 'pi pi-building' },
  { to: '/proyectos',     label: 'Proyectos',      icon: 'pi pi-bolt' },
  { to: '/fallas',        label: 'Monitoreo',         icon: 'pi pi-exclamation-triangle', roles: ['admin', 'operaciones', 'monitoreo'] },
  { to: '/liquidaciones', label: 'Liquidaciones',  icon: 'pi pi-dollar',               roles: ['admin', 'liquidaciones'] },
]

const navItems = computed(() => all.filter(i => !i.roles || auth.can(...i.roles)))
</script>

<style scoped>
.nav-item {
  color: rgba(253, 250, 247, 0.6);
}
.nav-item:hover {
  background-color: rgba(145, 91, 216, 0.12);
  color: #FDFAF7;
}
.nav-active {
  background-color: rgba(145, 91, 216, 0.2) !important;
  color: #FDFAF7 !important;
  border-left: 3px solid #915BD8;
  padding-left: calc(0.75rem - 3px);
  font-weight: 600;
}
.nav-active i {
  color: #915BD8;
}
</style>
