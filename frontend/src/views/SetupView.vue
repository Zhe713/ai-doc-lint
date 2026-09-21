<template>
  <div class="auth-page">
    <el-card class="auth-card">
      <template #header>
        <div class="title">初始化管理员</div>
      </template>
      <el-alert
        title="首次部署需要创建唯一的系统管理员账号，该页面仅在没有任何用户时出现一次。"
        type="info"
        :closable="false"
        style="margin-bottom: 16px"
      />
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent>
        <el-form-item label="管理员用户名" prop="username">
          <el-input v-model="form.username" placeholder="3-32 位，中英文/数字/下划线" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="至少 8 位" />
        </el-form-item>
        <el-form-item label="确认密码" prop="confirm">
          <el-input v-model="form.confirm" type="password" show-password />
        </el-form-item>
        <el-button type="primary" :loading="loading" style="width: 100%" @click="submit">
          创建管理员并进入系统
        </el-button>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'

import { createInitialAdmin } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()
const formRef = ref<FormInstance>()
const loading = ref(false)

const form = reactive({ username: '', password: '', confirm: '' })

const rules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 32, message: '长度 3-32 位', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, max: 128, message: '密码至少 8 位', trigger: 'blur' }
  ],
  confirm: [
    {
      validator: (_rule, value, callback) => {
        value === form.password ? callback() : callback(new Error('两次输入的密码不一致'))
      },
      trigger: 'blur'
    }
  ]
}

async function submit() {
  await formRef.value?.validate()
  loading.value = true
  try {
    await createInitialAdmin(form.username, form.password)
    ElMessage.success('管理员创建成功，请登录')
    auth.needsSetup = false
    router.push({ name: 'login' })
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail ?? '初始化失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #eef3fb 0%, #dfe9f7 100%);
}
.auth-card {
  width: 420px;
}
.title {
  font-size: 18px;
  font-weight: 600;
}
</style>
