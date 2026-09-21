<template>
  <div class="auth-page">
    <el-card class="auth-card">
      <template #header>
        <div class="title">注册账号</div>
      </template>
      <el-alert
        v-if="!auth.openRegistration"
        title="管理员已关闭开放注册。"
        type="warning"
        :closable="false"
        style="margin-bottom: 16px"
      />
      <el-form v-else ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent>
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="3-32 位，中英文/数字/下划线" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="至少 8 位" />
        </el-form-item>
        <el-form-item label="确认密码" prop="confirm">
          <el-input v-model="form.confirm" type="password" show-password />
        </el-form-item>
        <el-button type="primary" :loading="loading" style="width: 100%" @click="submit">
          注册并登录
        </el-button>
      </el-form>
      <div class="footer"><router-link to="/login">返回登录</router-link></div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'

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
    await auth.register(form.username, form.password)
    ElMessage.success('注册成功，正在登录')
    await auth.login(form.username, form.password)
    router.replace('/')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail ?? '注册失败')
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
.footer {
  text-align: center;
  margin-top: 12px;
  font-size: 13px;
}
</style>
