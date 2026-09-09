<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { authClient } from './auth'
import {
  api,
  ApiError,
  type Comment,
  type EventItem,
  type Me,
  type Priority,
  type Status,
  type Ticket,
} from './api'

const loading = ref(true)
const busy = ref(false)
const error = ref('')
const sessionEmail = ref<string | null>(null)
const me = ref<Me | null>(null)

const authMode = ref<'signin' | 'signup'>('signin')
const email = ref('')
const password = ref('')
const displayName = ref('')

const tickets = ref<Ticket[]>([])
const total = ref(0)
const selectedId = ref<string | null>(null)
const selected = ref<Ticket | null>(null)
const comments = ref<Comment[]>([])
const events = ref<EventItem[]>([])
const statusFilter = ref<Status | ''>('')
const query = ref('')

const newTitle = ref('')
const newDescription = ref('')
const newCategory = ref('General')
const newPriority = ref<Priority>('NORMAL')
const commentBody = ref('')
const commentInternal = ref(false)
const staffStatus = ref<Status>('IN_PROGRESS')

const isStaff = computed(() => me.value?.role === 'AGENT' || me.value?.role === 'ADMIN')

async function refreshSession() {
  const result = await authClient.getSession()
  if (result.data?.session && result.data?.user) {
    sessionEmail.value = result.data.user.email ?? result.data.user.name ?? 'signed in'
    me.value = await api.me()
  } else {
    sessionEmail.value = null
    me.value = null
  }
}

async function boot() {
  loading.value = true
  error.value = ''
  try {
    await refreshSession()
    if (me.value) await loadTickets()
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Failed to start'
  } finally {
    loading.value = false
  }
}

async function submitAuth() {
  busy.value = true
  error.value = ''
  try {
    const result =
      authMode.value === 'signup'
        ? await authClient.signUp.email({
            name: displayName.value.trim() || email.value.split('@')[0] || 'User',
            email: email.value.trim(),
            password: password.value,
          })
        : await authClient.signIn.email({
            email: email.value.trim(),
            password: password.value,
          })
    if (result.error) throw new Error(result.error.message)
    await refreshSession()
    await loadTickets()
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Auth failed'
  } finally {
    busy.value = false
  }
}

async function signOut() {
  await authClient.signOut()
  sessionEmail.value = null
  me.value = null
  tickets.value = []
  selected.value = null
  selectedId.value = null
}

async function loadTickets() {
  const params = new URLSearchParams({ page: '1', size: '50' })
  if (statusFilter.value) params.set('status', statusFilter.value)
  if (query.value.trim()) params.set('q', query.value.trim())
  const page = await api.listTickets(params)
  tickets.value = page.items
  total.value = page.total
  if (selectedId.value && !tickets.value.some((t) => t.id === selectedId.value)) {
    selectedId.value = null
    selected.value = null
  }
}

async function openTicket(id: string) {
  busy.value = true
  error.value = ''
  try {
    selectedId.value = id
    selected.value = await api.getTicket(id)
    staffStatus.value = selected.value.status === 'RESOLVED' ? 'OPEN' : 'IN_PROGRESS'
    const [c, e] = await Promise.all([api.listComments(id), api.listEvents(id)])
    comments.value = c.items
    events.value = e.items
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Failed to load ticket'
  } finally {
    busy.value = false
  }
}

async function createTicket() {
  busy.value = true
  error.value = ''
  try {
    const ticket = await api.createTicket({
      title: newTitle.value.trim(),
      description: newDescription.value.trim(),
      category: newCategory.value.trim(),
      priority: newPriority.value,
    })
    newTitle.value = ''
    newDescription.value = ''
    await loadTickets()
    await openTicket(ticket.id)
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Create failed'
  } finally {
    busy.value = false
  }
}

async function patchTicket(payload: {
  status?: Status
  assignee_id?: string | null
}) {
  if (!selected.value) return
  busy.value = true
  error.value = ''
  try {
    selected.value = await api.changeTicket(selected.value.id, {
      expected_version: selected.value.version,
      ...payload,
    })
    await loadTickets()
    await openTicket(selected.value.id)
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Update failed'
    if (selected.value) await openTicket(selected.value.id)
  } finally {
    busy.value = false
  }
}

async function sendComment() {
  if (!selected.value || !commentBody.value.trim()) return
  busy.value = true
  error.value = ''
  try {
    await api.addComment(selected.value.id, {
      body: commentBody.value.trim(),
      internal: isStaff.value ? commentInternal.value : false,
    })
    commentBody.value = ''
    commentInternal.value = false
    await openTicket(selected.value.id)
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Comment failed'
  } finally {
    busy.value = false
  }
}

watch([statusFilter, query], () => {
  if (me.value) void loadTickets().catch((err) => {
    error.value = err instanceof Error ? err.message : 'List failed'
  })
})

onMounted(() => {
  void boot()
})
</script>

<template>
  <div class="shell">
    <header class="brand">
      <div>
        <h1>Support</h1>
        <p>Tickets with explicit ownership. Auth via Neon; roles from the API.</p>
      </div>
      <div v-if="me" class="row">
        <span class="muted">{{ me.name }} · {{ me.role }}<template v-if="sessionEmail"> · {{ sessionEmail }}</template></span>
        <button class="secondary" type="button" @click="signOut">Sign out</button>
      </div>
    </header>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="loading" class="muted">Loading…</p>

    <section v-else-if="!me" class="panel grid" style="max-width: 28rem">
      <h2>{{ authMode === 'signup' ? 'Create account' : 'Sign in' }}</h2>
      <label v-if="authMode === 'signup'">
        Name
        <input v-model="displayName" autocomplete="name" />
      </label>
      <label>
        Email
        <input v-model="email" type="email" autocomplete="email" required />
      </label>
      <label>
        Password
        <input v-model="password" type="password" autocomplete="current-password" required />
      </label>
      <div class="row">
        <button type="button" :disabled="busy" @click="submitAuth">
          {{ authMode === 'signup' ? 'Sign up' : 'Sign in' }}
        </button>
        <button
          class="secondary"
          type="button"
          @click="authMode = authMode === 'signup' ? 'signin' : 'signup'"
        >
          {{ authMode === 'signup' ? 'Have an account?' : 'Need an account?' }}
        </button>
      </div>
    </section>

    <template v-else>
      <section class="panel grid">
        <div class="row">
          <label style="flex: 1">
            Search
            <input v-model="query" placeholder="Title or description" />
          </label>
          <label>
            Status
            <select v-model="statusFilter">
              <option value="">All</option>
              <option value="OPEN">OPEN</option>
              <option value="IN_PROGRESS">IN_PROGRESS</option>
              <option value="WAITING_CUSTOMER">WAITING_CUSTOMER</option>
              <option value="RESOLVED">RESOLVED</option>
            </select>
          </label>
          <button class="secondary" type="button" :disabled="busy" @click="loadTickets">
            Refresh
          </button>
        </div>
        <p class="muted">{{ total }} ticket(s)</p>
        <div class="list">
          <button
            v-for="ticket in tickets"
            :key="ticket.id"
            class="ticket"
            :class="{ active: ticket.id === selectedId }"
            type="button"
            @click="openTicket(ticket.id)"
          >
            <strong>{{ ticket.title }}</strong>
            <div class="meta">
              <span>{{ ticket.status }}</span>
              <span>{{ ticket.priority }}</span>
              <span>{{ ticket.category }}</span>
            </div>
          </button>
        </div>
      </section>

      <section v-if="!isStaff" class="panel grid">
        <h2>New ticket</h2>
        <div class="grid two">
          <label>
            Title
            <input v-model="newTitle" maxlength="160" />
          </label>
          <label>
            Category
            <input v-model="newCategory" maxlength="60" />
          </label>
        </div>
        <label>
          Description
          <textarea v-model="newDescription" maxlength="8000" />
        </label>
        <label>
          Priority
          <select v-model="newPriority">
            <option value="LOW">LOW</option>
            <option value="NORMAL">NORMAL</option>
            <option value="HIGH">HIGH</option>
          </select>
        </label>
        <button type="button" :disabled="busy" @click="createTicket">Create</button>
      </section>

      <section v-if="selected" class="panel grid">
        <h2>{{ selected.title }}</h2>
        <div class="meta">
          <span>{{ selected.status }}</span>
          <span>v{{ selected.version }}</span>
          <span>{{ selected.priority }}</span>
          <span>{{ selected.category }}</span>
        </div>
        <p>{{ selected.description }}</p>

        <div v-if="isStaff" class="row">
          <label>
            Move to
            <select v-model="staffStatus">
              <option value="OPEN">OPEN</option>
              <option value="IN_PROGRESS">IN_PROGRESS</option>
              <option value="WAITING_CUSTOMER">WAITING_CUSTOMER</option>
              <option value="RESOLVED">RESOLVED</option>
            </select>
          </label>
          <button type="button" :disabled="busy" @click="patchTicket({ status: staffStatus })">
            Update status
          </button>
          <button
            class="secondary"
            type="button"
            :disabled="busy"
            @click="patchTicket({ assignee_id: me!.id, status: 'IN_PROGRESS' })"
          >
            Assign to me
          </button>
        </div>

        <div v-else-if="selected.status === 'RESOLVED'" class="row">
          <button type="button" :disabled="busy" @click="patchTicket({ status: 'OPEN' })">
            Reopen
          </button>
        </div>

        <div class="grid two">
          <div class="stack">
            <h3>Comments</h3>
            <div v-for="item in comments" :key="item.id" class="note" :class="{ internal: item.internal }">
              <div class="meta">
                <span>{{ item.internal ? 'internal' : 'public' }}</span>
                <span>{{ new Date(item.created_at).toLocaleString() }}</span>
              </div>
              <p>{{ item.body }}</p>
            </div>
            <label>
              Reply
              <textarea v-model="commentBody" />
            </label>
            <label v-if="isStaff" class="row">
              <input v-model="commentInternal" type="checkbox" />
              Internal note
            </label>
            <button type="button" :disabled="busy" @click="sendComment">Post</button>
          </div>
          <div class="stack">
            <h3>Events</h3>
            <div v-for="item in events" :key="item.id" class="note" :class="{ internal: item.internal }">
              <div class="meta">
                <span>{{ item.action }}</span>
                <span>{{ item.internal ? 'internal' : 'public' }}</span>
                <span>{{ new Date(item.created_at).toLocaleString() }}</span>
              </div>
            </div>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>
