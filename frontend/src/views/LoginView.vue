<template>
  <div class="auth-page">
    <el-card class="auth-card">
      <template #header>
        <div class="brand">
          <div class="title">ai-doc-lint</div>
          <div class="subtitle">AI 文档校验 · 让 AI 做校对，行家做判断</div>
        </div>
      </template>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent>
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" prefix-icon="User" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            prefix-icon="Lock"
            show-password
            @keyup.enter="submit"
          />
        </el-form-item>
        <el-button type="primary" :loading="loading" style="width: 100%" @click="submit">
          登录
        </el-button>
      </el-form>
      <div v-if="auth.openRegistration" class="footer">
        还没有账号？<router-link to="/register">注册</router-link>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'

import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

async function submit() {
  await formRef.value?.validate()
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    ElMessage.success('登录成功')
    router.replace((route.query.redirect as string) || '/')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail ?? '登录失败')
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
  width: 400px;
}
.brand {
  text-align: center;
}
.title {
  font-size: 20px;
  font-weight: 700;
}
.subtitle {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.footer {
  text-align: center;
  margin-top: 12px;
  font-size: 13px;
}
</style>
