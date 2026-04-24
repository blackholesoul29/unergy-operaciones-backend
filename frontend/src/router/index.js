import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes = [
  { path: '/login', name: 'Login', component: () => import('@/views/LoginView.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('@/App.vue'),
    children: [
      { path: '', redirect: '/dashboard' },
      { path: 'dashboard', name: 'Dashboard', component: () => import('@/views/DashboardView.vue') },
      { path: 'clientes', name: 'Clientes', component: () => import('@/views/Clientes/ClientesListView.vue') },
      { path: 'proyectos', name: 'Proyectos', component: () => import('@/views/Proyectos/ProyectosListView.vue') },
      { path: 'proyectos/:id', name: 'ProyectoDetalle', component: () => import('@/views/Proyectos/ProyectoDetailView.vue') },
      { path: 'fallas', name: 'Fallas', component: () => import('@/views/Fallas/FallasListView.vue'), meta: { roles: ['admin', 'operaciones', 'monitoreo'] } },
      { path: 'liquidaciones', name: 'Liquidaciones', component: () => import('@/views/Liquidaciones/LiquidacionesListView.vue'), meta: { roles: ['admin', 'liquidaciones'] } },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isAuthenticated) return '/login'
  if (to.meta.roles && !auth.can(...to.meta.roles)) return '/dashboard'
})

export default router
