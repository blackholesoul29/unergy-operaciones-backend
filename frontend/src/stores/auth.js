import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/api/client'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || null)
  const user = ref(JSON.parse(localStorage.getItem('user') || 'null'))

  const isAuthenticated = computed(() => !!token.value)
  const role = computed(() => user.value?.rol || null)

  function can(...roles) {
    return roles.includes(role.value) || role.value === 'admin'
  }

  async function login(email, password) {
    const resp = await fetch('/api/v1/auth/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ username: email, password }),
    })
    const data = await resp.json()
    if (!resp.ok) throw { response: { data } }
    token.value = data.access_token
    localStorage.setItem('token', data.access_token)
    // JWT usa base64URL — hay que convertir antes de atob
    const b64 = data.access_token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
    const payload = JSON.parse(atob(b64.padEnd(b64.length + (4 - b64.length % 4) % 4, '=')))
    user.value = { id: payload.sub, rol: payload.rol, nombre: payload.nombre, email: payload.email }
    localStorage.setItem('user', JSON.stringify(user.value))
  }

  function logout() {
    token.value = null
    user.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('user')
  }

  return { token, user, isAuthenticated, role, can, login, logout }
})
