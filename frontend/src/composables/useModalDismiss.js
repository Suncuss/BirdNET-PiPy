import { onUnmounted, unref, watch } from 'vue'

const activeEntries = []
let isListening = false
let isScrollLocked = false
let previousBodyOverflow = ''

const resolve = (value) => (typeof value === 'function' ? value() : unref(value))

const syncDocumentState = () => {
  if (typeof document === 'undefined') return

  const shouldListen = activeEntries.some(entry => entry.closeOnEscape)
  if (shouldListen && !isListening) {
    document.addEventListener('keydown', handleDocumentKeydown)
    isListening = true
  } else if (!shouldListen && isListening) {
    document.removeEventListener('keydown', handleDocumentKeydown)
    isListening = false
  }

  const shouldLockScroll = activeEntries.some(entry => entry.lockScroll)
  if (shouldLockScroll && !isScrollLocked) {
    previousBodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    isScrollLocked = true
  } else if (!shouldLockScroll && isScrollLocked) {
    document.body.style.overflow = previousBodyOverflow
    previousBodyOverflow = ''
    isScrollLocked = false
  }
}

const handleDocumentKeydown = (event) => {
  if (event.key !== 'Escape') return

  const entry = [...activeEntries].reverse().find(item => item.closeOnEscape)
  entry?.requestDismiss(event)
}

const activate = (entry) => {
  if (!activeEntries.includes(entry)) {
    activeEntries.push(entry)
    syncDocumentState()
  }
}

const deactivate = (entry) => {
  const index = activeEntries.indexOf(entry)
  if (index !== -1) {
    activeEntries.splice(index, 1)
    syncDocumentState()
  }
}

export function useModalDismiss(isVisible, onDismiss, options = {}) {
  const visibleSource = isVisible ?? true
  const canDismiss = options.canDismiss ?? true

  const entry = {
    closeOnEscape: options.closeOnEscape !== false,
    lockScroll: options.lockScroll !== false,
    requestDismiss: (event) => {
      if (!resolve(canDismiss)) return
      return onDismiss(event)
    }
  }

  watch(
    () => Boolean(resolve(visibleSource)),
    (visible) => {
      if (visible) activate(entry)
      else deactivate(entry)
    },
    { immediate: true }
  )

  onUnmounted(() => {
    deactivate(entry)
  })

  return {
    requestDismiss: entry.requestDismiss
  }
}
