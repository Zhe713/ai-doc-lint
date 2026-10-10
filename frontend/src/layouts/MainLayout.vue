<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="logo">ai-doc-lint</div>
      <el-menu :default-active="route.path" router class="menu" background-color="#1f2d3d"
        text-color="#bfcbd9" active-text-color="#ffffff">
        <el-menu-item index="/">
          <el-icon><HomeFilled /></el-icon><span>工作台</span>
        </el-menu-item>
        <el-menu-item index="/documents">
          <el-icon><Document /></el-icon><span>文档校验</span>
        </el-menu-item>
        <el-menu-item index="/compare">
          <el-icon><Connection /></el-icon><span>交叉比对</span>
        </el-menu-item>
        <el-menu-item index="/chat">
          <el-icon><ChatDotRound /></el-icon><span>文档助手</span>
        </el-menu-item>
        <el-menu-item index="/rules">
          <el-icon><SetUp /></el-icon><span>规则与模板（W3/W6）</span>
        </el-menu-item>
        <el-menu-item index="/search">
          <el-icon><Search /></el-icon><span>语义检索</span>
        </el-menu-item>
        <el-sub-menu v-if="auth.isAdmin" index="admin">
          <template #title>
            <el-icon><Setting /></el-icon><span>系统管理</span>
          </template>
          <el-menu-item index="/admin/users">用户管理</el-menu-item>
          <el-menu-item index="/admin/settings">系统设置</el-menu-item>
        </el-sub-menu>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="header-title">自托管 AI 文档校验工具</div>
        <el-dropdown @command="onCommand">
          <span class="user-area">
            <el-icon><UserFilled /></el-icon>
            {{ auth.user?.username }}
            <el-tag v-if="auth.isAdmin" size="small" type="danger" effect="plain" style="margin-left: 6px">
              管理员
            </el-tag>
            <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'

import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

async function onCommand(command: string) {
  if (command === 'logout') {
    await ElMessageBox.confirm('确定退出登录吗？', '提示', { type: 'warning' })
    await auth.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.layout {
  height: 100vh;
}
.aside {
  background: #1f2d3d;
  color: #fff;
}
.logo {
  height: 60px;
  line-height: 60px;
  text-align: center;
  font-weight: 700;
  font-size: 17px;
  letter-spacing: 0.5px;
  border-bottom: 1px solid #2a3a4d;
}
.menu {
  border-right: none;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
}
.header-title {
  font-weight: 600;
}
.user-area {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  outline: none;
}
</style>
