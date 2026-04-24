<template>
  <form @submit.prevent="submit" class="space-y-4 pt-2">
    <div class="grid grid-cols-2 gap-4">
      <div class="col-span-2">
        <label class="field-label">Razón social / Nombre *</label>
        <InputText v-model="f.razon_social_nombre" class="w-full" required />
      </div>
      <div>
        <label class="field-label">NIT / Cédula</label>
        <InputText v-model="f.nit_cedula" class="w-full" />
      </div>
      <div>
        <label class="field-label">Tipo de persona</label>
        <Select v-model="f.tipo_persona" :options="['natural', 'juridica']" class="w-full" placeholder="Seleccionar" showClear />
      </div>
      <div>
        <label class="field-label">Representante legal</label>
        <InputText v-model="f.representante_legal" class="w-full" />
      </div>
      <div>
        <label class="field-label">Correo</label>
        <InputText v-model="f.correo_electronico" type="email" class="w-full" />
      </div>
      <div>
        <label class="field-label">Teléfono</label>
        <InputText v-model="f.telefono_contacto" class="w-full" />
      </div>
      <div>
        <label class="field-label">Ciudad</label>
        <InputText v-model="f.ciudad" class="w-full" />
      </div>
      <div class="col-span-2">
        <label class="field-label">Dirección</label>
        <InputText v-model="f.direccion" class="w-full" />
      </div>
      <div>
        <label class="field-label">IVA %</label>
        <InputNumber v-model="f.iva_pct" :maxFractionDigits="2" class="w-full" />
      </div>
      <div>
        <label class="field-label">Retención %</label>
        <InputNumber v-model="f.retencion_pct" :maxFractionDigits="2" class="w-full" />
      </div>
      <div>
        <label class="field-label">ReteICA %</label>
        <InputNumber v-model="f.reteica_pct" :maxFractionDigits="4" class="w-full" />
      </div>
    </div>

    <div class="flex justify-end gap-2 pt-2">
      <Button type="button" label="Cancelar" severity="secondary" @click="$emit('cancel')" />
      <Button type="submit" label="Guardar" />
    </div>
  </form>
</template>

<script setup>
import { reactive, watch } from 'vue'
import InputText from 'primevue/inputtext'
import InputNumber from 'primevue/inputnumber'
import Select from 'primevue/select'
import Button from 'primevue/button'

const props = defineProps({ initial: Object })
const emit = defineEmits(['save', 'cancel'])

const f = reactive({ ...props.initial })
watch(() => props.initial, (v) => Object.assign(f, v), { deep: true })

function submit() {
  const payload = {}
  for (const [k, v] of Object.entries(f)) {
    if (v !== null && v !== undefined && v !== '') payload[k] = v
  }
  emit('save', payload)
}
</script>

<style scoped>
.field-label { @apply block text-xs font-medium text-gray-600 mb-1; }
</style>
