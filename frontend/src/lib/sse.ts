import { useEffect, useRef } from 'react'

export interface AppEvent {
  event: string
  data: Record<string, unknown>
}

/** Subscribe to the project's SSE stream; handler is kept fresh via ref. */
export function useProjectEvents(pid: string | undefined, handler: (e: AppEvent) => void) {
  const handlerRef = useRef(handler)
  handlerRef.current = handler

  useEffect(() => {
    if (!pid) return
    const source = new EventSource(`/api/projects/${pid}/events`)
    source.onmessage = (msg) => {
      try {
        handlerRef.current(JSON.parse(msg.data))
      } catch {
        /* keepalive or malformed */
      }
    }
    return () => source.close()
  }, [pid])
}
