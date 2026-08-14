/**
 * Service Worker — handles Web Push notifications for TLS-Decoded Cloud.
 *
 * The backend sends a push payload of:
 *   { title: string, body: string, url?: string }
 *
 * The SW shows a native notification and, when clicked, navigates to
 * the app (defaults to '/').
 */

self.addEventListener('push', function (event) {
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch {
    data = { title: 'TLS-Decoded', body: event.data?.text() ?? 'New notification' }
  }

  const title = data.title ?? 'TLS-Decoded'
  const options = {
    body: data.body ?? '',
    icon: '/favicon.ico',
    badge: '/favicon.ico',
    tag: data.tag ?? 'tls-decoded-notification',
    data: { url: data.url ?? '/' },
    requireInteraction: false,
  }

  event.waitUntil(self.registration.showNotification(title, options))
})

self.addEventListener('notificationclick', function (event) {
  event.notification.close()
  const url = event.notification.data?.url ?? '/'
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (windowClients) {
      // If the app is already open, focus it
      for (const client of windowClients) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          return client.focus()
        }
      }
      // Otherwise open a new window
      if (clients.openWindow) {
        return clients.openWindow(url)
      }
    })
  )
})
