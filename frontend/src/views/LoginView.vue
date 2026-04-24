<template>
  <div class="min-h-screen flex items-center justify-center bg-gray-900">
    <div class="bg-white rounded-2xl shadow-xl p-10 w-full max-w-sm">
      <div class="text-center mb-8">
        <span class="text-3xl font-bold text-green-500">Unergy</span>
        <p class="text-gray-500 text-sm mt-1">Plataforma de Operaciones</p>
      </div>

      <form @submit.prevent="submit" class="space-y-5">
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">Correo</label>
          <InputText v-model="email" type="email" placeholder="tu@unergy.io" class="w-full" required />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">Contraseña</label>
          <Password v-model="password" :feedback="false" class="w-full" inputClass="w-full" placeholder="••••••••" required />
        </div>
        <Message v-if="error" severity="error" :closable="false" class="text-sm">{{ error }}</Message>
        <Button type="submit" label="Ingresar" class="w-full" :loading="loading" />
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import InputText from 'primevue/inputtext'
import Password from 'primevue/password'
import Button from 'primevue/button'
import Message from 'primevue/message'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const email = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

async function submit() {
  loading.value = true
  error.value = ''
  try {
    await auth.login(email.value, password.value)
    router.push('/dashboard')
  } catch (e) {
    error.value = e.response?.data?.detail || 'Credenciales incorrectas'
  } finally {
    loading.value = false
  }
}
</script>
