<template>
  <div class="monitoreo-wrapper">
    <!-- spinner mientras carga el iframe -->
    <div v-if="loading" class="monitoreo-loading">
      <div class="spin-ring" />
      <span>Cargando monitoreo…</span>
    </div>

    <iframe
      v-show="!loading"
      ref="iframeRef"
      :src="iframeSrc"
      class="monitoreo-iframe"
      title="Monitoreo de fallas"
      allow="clipboard-write"
      @load="onIframeLoad"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const iframeRef = ref(null)
const loading = ref(true)

// VITE_BACKEND_URL debe apuntar a la raíz del backend (sin /api/v1).
// Dev:  http://localhost:8000   (definido en .env.development)
// Prod: https://backend-production-63d8.up.railway.app  (definido en .env.production)
const backendUrl = (import.meta.env.VITE_BACKEND_URL ?? 'http://localhost:8000').replace(/\/$/, '')

const iframeSrc = computed(() => {
  const token = auth.token
  if (!token) return ''
  // El monitoreo se sirve desde el backend Railway como archivo estático.
  // Las llamadas /api/v1/monitoreo/* que hace fallas-unergy son same-origin
  // respecto al iframe, así que no hay problemas de CORS.
  return `${backendUrl}/monitoreo?token=${encodeURIComponent(token)}`
})

function onIframeLoad() {
  loading.value = false
}

onMounted(() => {
  // Si el token ya expiró, el guardia del router debería haber redirigido.
  // Solo un guard extra para evitar mostrar un iframe sin token.
  if (!auth.token) {
    loading.value = false
  }
})
</script>

<style scoped>
/* El <main> de App.vue ya tiene overflow:hidden + p-0 cuando estamos en /fallas.
   Este wrapper solo necesita ocupar el 100% del espacio que le cede el main. */
.monitoreo-wrapper {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #1a1025;
}

.monitoreo-iframe {
  flex: 1;
  width: 100%;
  border: none;
  display: block;
}

.monitoreo-loading {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: #9b89b5;
  font-size: 14px;
}

.spin-ring {
  width: 36px;
  height: 36px;
  border: 3px solid rgba(145, 91, 216, 0.2);
  border-top-color: #915BD8;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
